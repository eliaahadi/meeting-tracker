import os
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

from flask import Flask, request, jsonify, send_from_directory, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime, timedelta
import datetime as dt
import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

app = Flask(__name__, static_folder="frontend")
CORS(app)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///meetings.db'
db = SQLAlchemy(app)

GOOGLE_CREDENTIALS_FILE = 'credentials.json'
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
TOKEN_FILE = 'token.json'

class Meeting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200))
    description = db.Column(db.Text)
    date = db.Column(db.Date)
    start_time = db.Column(db.Time)
    end_time = db.Column(db.Time)
    attendees = db.Column(db.Text)
    calendar_name = db.Column(db.String(100))

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
    timeframe = request.args.get('range', 'all')
    today = datetime.now().date()

    if timeframe == 'week':
        start_date = today - timedelta(days=today.weekday())  # Monday of this week
    elif timeframe == 'month':
        start_date = today.replace(day=1)  # 1st of this month
    elif timeframe == 'last7':
        start_date = today - timedelta(days=6)  # last 7 days including today
    else:
        start_date = None

    query = Meeting.query
    if start_date:
        query = query.filter(Meeting.date >= start_date)

    meetings = query.order_by(Meeting.date.desc(), Meeting.start_time.desc()).all()

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

    now = dt.datetime.now().isoformat() + 'Z'
    events_result = service.events().list(
        calendarId='primary',
        timeMin=now,
        maxResults=20,
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    events = events_result.get('items', [])
    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date'))
        end = event['end'].get('dateTime', event['end'].get('date'))

        new_meeting = Meeting(
            title=event.get('summary', 'No Title'),
            description=event.get('description', ''),
            date=dt.datetime.fromisoformat(start).date(),
            start_time=dt.datetime.fromisoformat(start).time(),
            end_time=dt.datetime.fromisoformat(end).time(),
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

    db.session.commit()
    return f'{len(events)} events synced.'

@app.route('/')
@app.route('/<path:path>')
def serve_frontend(path="index.html"):
    return send_from_directory(app.static_folder, path)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))