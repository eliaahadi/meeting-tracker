import os
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

from flask import Flask, request, jsonify, send_from_directory, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime, timedelta, date
from sqlalchemy import cast, Date
import datetime as dt
import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

# app = Flask(__name__, static_folder='static', static_url_path='')
# basedir = os.path.abspath(os.path.dirname(__file__))
# app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(basedir, "meetings.db")}'
# app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///meetings.db'
# app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# ✅ Absolute path to keep DB consistent
BASE_DIR = '/Users/eliaahadi/Library/CloudStorage/GoogleDrive-elia.ahadi@gmail.com/My Drive/Personal/Coding/meeting_tracker'
DB_PATH = os.path.join(BASE_DIR, 'meetings.db')

# Make sure the directory exists
os.makedirs(BASE_DIR, exist_ok=True)

app = Flask(__name__, static_folder='static')
CORS(app)

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

GOOGLE_CREDENTIALS_FILE = 'credentials.json'
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
TOKEN_FILE = 'token.json'

class Meeting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255))
    description = db.Column(db.Text)
    date = db.Column(db.Date)
    start_time = db.Column(db.Time)
    end_time = db.Column(db.Time)
    attendees = db.Column(db.Text)
    calendar_name = db.Column(db.String(255))

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "date": self.date.isoformat() if self.date else None,
            "start_time": self.start_time.strftime("%H:%M") if self.start_time else None,
            "end_time": self.end_time.strftime("%H:%M") if self.end_time else None,
            "attendees": self.attendees,
            "calendar_name": self.calendar_name,
        }
    

@app.route('/api/log-event', methods=['POST'])
def log_event():
    data = request.json
    try:
        start_dt = datetime.fromisoformat(data.get('start_time'))
        end_dt = datetime.fromisoformat(data.get('end_time'))
        new_meeting = Meeting(
            title=data.get('title'),
            description=data.get('description'),
            date=start_dt.date(),
            start_time=start_dt.time(),
            end_time=end_dt.time(),
            attendees=', '.join(data.get('attendees', [])),
            calendar_name=data.get('calendar_name')
        )
        db.session.add(new_meeting)
        db.session.commit()
        return jsonify({'message': 'Meeting logged successfully'}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/meetings', methods=['GET'])
def get_meetings():
    meetings = Meeting.query.order_by(Meeting.date.desc(), Meeting.start_time.desc()).all()
    result = []
    total_duration = 0
    for m in meetings:
        start = datetime.combine(m.date, m.start_time)
        end = datetime.combine(m.date, m.end_time)
        duration = (end - start).seconds // 60
        total_duration += duration
        result.append({
            'title': m.title,
            'description': m.description,
            'date': m.date.strftime('%Y-%m-%d'),
            'start_time': m.start_time.strftime('%H:%M'),
            'end_time': m.end_time.strftime('%H:%M'),
            'attendees': m.attendees,
            'calendar_name': m.calendar_name,
            'duration_min': duration
        })
    return jsonify({
        'meetings': result,
        'summary': {
            'count': len(meetings),
            'total_duration': total_duration,
            'average_duration': total_duration // len(meetings) if meetings else 0
        }
    })

@app.route('/api/meetings/filter')
def get_filtered_meetings():
    range_filter = request.args.get('range', 'all')
    today = date.today()

    start_date = None
    end_date = None

    if range_filter == 'last7':
        start_date = today - timedelta(days=7)
        end_date = today
    elif range_filter == 'week':
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=7)
    elif range_filter == 'month':
        start_date = today.replace(day=1)
        next_month = today.replace(day=28) + timedelta(days=4)
        end_date = next_month.replace(day=1)
    
    print(f"🕒 System date is: {today}")
    print(f"🧠 Filtering for: {range_filter}, start_date = {start_date}, end_date = {end_date}")

    all_meetings = Meeting.query.all()
    if start_date and end_date:
        filtered = [m for m in all_meetings if start_date <= m.date < end_date]
    elif start_date:
        filtered = [m for m in all_meetings if m.date >= start_date]
    else:
        filtered = all_meetings

    print("📍 Filtered DB dates:")
    for m in filtered:
        print(" -", m.date, type(m.date))
    print("📊 Filtered count =", len(filtered))

    return jsonify([m.to_dict() for m in filtered])

@app.route('/authorize')
def authorize():
    flow = Flow.from_client_secrets_file(
        GOOGLE_CREDENTIALS_FILE,
        scopes=SCOPES,
        redirect_uri='http://localhost:5000/oauth2callback'
    )
    auth_url, _ = flow.authorization_url(prompt='consent')
    return redirect(auth_url)

@app.route('/oauth2callback')
def oauth2callback():
    try:
        flow = Flow.from_client_secrets_file(
            GOOGLE_CREDENTIALS_FILE,
            scopes=SCOPES,
            redirect_uri='http://localhost:5000/oauth2callback'
        )
        flow.fetch_token(authorization_response=request.url)
        creds = flow.credentials
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
        print("✅ OAuth successful, token saved.")
        return redirect('/')
    except Exception as e:
        print("❌ OAuth failed:", e)
        return jsonify({"error": str(e)}), 500

@app.route('/sync-calendar')
def sync_calendar():
    if not os.path.exists(TOKEN_FILE):
        return 'Authorize first at /authorize', 401

    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    service = build('calendar', 'v3', credentials=creds)

    # Get meetings from past 30 days
    time_min = (datetime.utcnow() - timedelta(days=30)).isoformat() + 'Z'
    time_max = (datetime.utcnow() + timedelta(days=30)).isoformat() + 'Z'

    events_result = service.events().list(
        calendarId='primary',
        timeMin=time_min,
        timeMax=time_max,
        maxResults=100,
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    events = events_result.get('items', [])
    count = 0

    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date'))
        end = event['end'].get('dateTime', event['end'].get('date'))

        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)

        new_meeting = Meeting(
            title=event.get('summary', 'No Title'),
            description=event.get('description', ''),
            date=start_dt.date(),
            start_time=start_dt.time(),
            end_time=end_dt.time(),
            attendees=', '.join([att.get('email') for att in event.get('attendees', [])]),
            calendar_name='primary'
        )

        exists = Meeting.query.filter_by(
            title=new_meeting.title,
            date=new_meeting.date,
            start_time=new_meeting.start_time
        ).first()

        if not exists:
            db.session.add(new_meeting)
            count += 1

    db.session.commit()
    return f'{count} events synced.'

@app.route('/')
def serve_index():
    return send_from_directory('frontend', 'index.html')

@app.route('/<path:path>')
def serve_frontend(path="index.html"):
    return send_from_directory(app.static_folder, path)


if __name__ == '__main__':
    with app.app_context():
        # db.drop_all() 
        db.create_all()  # ✅ no drop_all needed now
        print("\n ✅ Tables created \n")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))