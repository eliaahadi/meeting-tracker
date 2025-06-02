from flask import Flask, request, jsonify, send_from_directory, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime, timedelta, date
from sqlalchemy import cast, Date
import os
import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

# ── Flask & SQLite config ──
app = Flask(__name__, static_folder="frontend", static_url_path='')
CORS(app)
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "meetings.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ── Google OAuth config ──
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
GOOGLE_CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# ── Inside app.py, update Meeting model ──

class Meeting(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    event_id    = db.Column(db.String(200), unique=True, nullable=False)  # new
    title       = db.Column(db.String(200))
    description = db.Column(db.Text)
    date        = db.Column(db.Date)
    start_time  = db.Column(db.Time)
    end_time    = db.Column(db.Time)
    attendees   = db.Column(db.Text)
    calendar_name = db.Column(db.String(100))

    def to_dict(self):
        return {
            "id": self.id,
            "event_id": self.event_id,
            "title": self.title,
            "description": self.description,
            "date": self.date.isoformat() if self.date else None,
            "start_time": self.start_time.strftime("%H:%M") if self.start_time else None,
            "end_time": self.end_time.strftime("%H:%M") if self.end_time else None,
            "attendees": self.attendees,
            "calendar_name": self.calendar_name,
        }

# ── Filtered meetings endpoint with keyword & category ──
@app.route('/api/meetings/filter')
def get_filtered_meetings():
    # 1) Read query parameters
    range_filter = request.args.get('range', 'all')
    keyword     = request.args.get('keyword', '').strip().lower()   # e.g. "project"
    category    = request.args.get('category', '').strip().lower()  # e.g. "#team" or "blue"

    today = date.today()
    print("🕒 System date is:", today)

    # 2) Determine start/end dates
    start_date = None
    end_date   = None

    if range_filter == 'last7':
        start_date = today - timedelta(days=7)
        end_date   = today
    elif range_filter == 'week':
        start_date = today - timedelta(days=today.weekday())  # Monday
        end_date   = start_date + timedelta(days=7)
    elif range_filter == 'month':
        start_date = today.replace(day=1)                     # first day of month
        next_month = (today.replace(day=28) + timedelta(days=4))
        end_date   = next_month.replace(day=1)                # first day of next month
    
    print(f"🧠 Filtering for: {range_filter}, start_date = {start_date}, end_date = {end_date}")
    print(f"🔍 Keyword filter: '{keyword}', Category filter: '{category}'")

    # 3) Fetch all meetings from DB
    all_meetings = Meeting.query.order_by(Meeting.date.desc(), Meeting.start_time.desc()).all()

    # 4) Apply date filter
    filtered = []
    for m in all_meetings:
        meets_date = m.date
        if start_date and end_date:
            if not (start_date <= meets_date < end_date):
                continue
        elif start_date and not end_date:
            if meets_date < start_date:
                continue
        # else, range_filter == 'all' → keep all

        filtered.append(m)

    print(f"📍 After date‐filter count: {len(filtered)}")

    # 5) Apply keyword + category filters (case‐insensitive substring match)
    if keyword:
        temp = []
        for m in filtered:
            title_lower = (m.title or "").lower()
            desc_lower  = (m.description or "").lower()
            if keyword in title_lower or keyword in desc_lower:
                temp.append(m)
        filtered = temp
        print(f"📍 After keyword‐filter ('{keyword}') count: {len(filtered)}")

    if category:
        temp = []
        for m in filtered:
            title_lower = (m.title or "").lower()
            desc_lower  = (m.description or "").lower()
            if category in title_lower or category in desc_lower:
                temp.append(m)
        filtered = temp
        print(f"📍 After category‐filter ('{category}') count: {len(filtered)}")

    # 6) Log final count
    print(f"📊 Final filtered count = {len(filtered)}")

    # 7) Return JSON list
    return jsonify([m.to_dict() for m in filtered])


# ── Other routes (authorize, sync, serve_frontend) stay unchanged ──

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
    flow = Flow.from_client_secrets_file(
        GOOGLE_CREDENTIALS_FILE,
        scopes=SCOPES,
        redirect_uri='http://localhost:5000/oauth2callback'
    )
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials
    with open(TOKEN_FILE, 'w') as token:
        token.write(creds.to_json())
    return redirect('/')

@app.route('/sync-calendar')
def sync_calendar():
    if not os.path.exists(TOKEN_FILE):
        return 'Authorize first at /authorize', 401

    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    service = build('calendar', 'v3', credentials=creds)

    # Fetch events from past 30 days to next 30 days
    now = datetime.utcnow()
    time_min = (now - timedelta(days=30)).isoformat() + 'Z'
    time_max = (now + timedelta(days=30)).isoformat() + 'Z'

    events_result = service.events().list(
        calendarId='primary',
        timeMin=time_min,
        timeMax=time_max,
        maxResults=250,
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    events = events_result.get('items', [])
    fetched_ids = set()

    for event in events:
        # 1) Make sure we have an event ID
        eid = event.get('id')
        if not eid:
            print("⚠️ Skipping event with no ID:", event.get('summary', '(no title)'))
            continue
        fetched_ids.add(eid)

        # 2) Parse start/end
        raw_start = event['start'].get('dateTime', event['start'].get('date'))
        raw_end   = event['end'].get('dateTime', event['end'].get('date'))
        try:
            start_dt = datetime.fromisoformat(raw_start)
            end_dt   = datetime.fromisoformat(raw_end)
        except Exception as parse_err:
            print("⚠️ Unable to parse dates:", raw_start, raw_end, parse_err)
            continue

        # 3) Build the fields
        meeting_date  = start_dt.date()
        meeting_title = event.get('summary', 'No Title') or 'No Title'
        meeting_desc  = event.get('description', '') or ''
        attendees_list = []
        for att in event.get('attendees', []):
            email = att.get('email')
            if email:
                attendees_list.append(email)
        meeting_attendees = ', '.join(attendees_list)
        cal_name = 'primary'

        # 4) Upsert logic
        existing = Meeting.query.filter_by(event_id=eid).first()
        if existing:
            # Update only if something changed
            changed = False
            if existing.title != meeting_title:
                existing.title = meeting_title
                changed = True
            if existing.description != meeting_desc:
                existing.description = meeting_desc
                changed = True
            if existing.date != meeting_date:
                existing.date = meeting_date
                changed = True
            if existing.start_time != start_dt.time():
                existing.start_time = start_dt.time()
                changed = True
            if existing.end_time != end_dt.time():
                existing.end_time = end_dt.time()
                changed = True
            if existing.attendees != meeting_attendees:
                existing.attendees = meeting_attendees
                changed = True
            if existing.calendar_name != cal_name:
                existing.calendar_name = cal_name
                changed = True

            if changed:
                db.session.add(existing)
                print(f"🔄 Updated event {eid} ({meeting_title})")
        else:
            # Insert new row
            new_meeting = Meeting(
                event_id=eid,
                title=meeting_title,
                description=meeting_desc,
                date=meeting_date,
                start_time=start_dt.time(),
                end_time=end_dt.time(),
                attendees=meeting_attendees,
                calendar_name=cal_name
            )
            db.session.add(new_meeting)
            print(f"➕ Added event {eid} ({meeting_title})")

    # 5) Delete any local rows whose event_id is no longer in Google’s results
    if fetched_ids:
        deleted = Meeting.query.filter(Meeting.event_id.notin_(list(fetched_ids))).delete(
            synchronize_session=False
        )
        if deleted:
            print(f"🗑️  Deleted {deleted} orphaned meeting(s)")

    db.session.commit()
    return f'{len(fetched_ids)} events synced (addition/update), purged orphans.'


@app.route('/')
@app.route('/<path:path>')
def serve_frontend(path="index.html"):
    return send_from_directory(app.static_folder, path)


if __name__ == "__main__":
    with app.app_context():
        # db.drop_all() 
        db.create_all()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))