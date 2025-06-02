# 🗓️ Meeting Tracker

A simple Flask-based web app that tracks your professional meetings from Google Calendar and shows helpful summaries like total count, weekly filters, and more — perfect for productivity review.

## ✨ Features

- 🔗 Google Calendar integration
- 📊 Visual meeting count summaries
- 📆 Filter by: All, This Week, Last 7 Days, This Month
- 🧾 View detailed meeting titles, times, and attendees

## 🛠️ Tech Stack

- Python (Flask)
- SQLite (via SQLAlchemy)
- Google Calendar API (OAuth2)
- HTML/CSS/JS frontend

---

## 🚀 Getting Started

### 1. Clone the Repo

```bash
git clone https://github.com/eliaahadi/meeting-tracker.git
cd meeting-tracker
```

### 2. Create a Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Set Up Google API Credentials
- Create a project at Google Cloud Console
- Enable Google Calendar API
- Create OAuth 2.0 credentials and download the credentials.json file
- Place it in the root of your project directory

 ### 5. Run the App Locally
 ```bash
python3 app.py
```

Visit: http://localhost:5000

🔄 Sync Your Calendar
1. Go to http://localhost:5000/authorize to connect your Google account
2. Then go to http://localhost:5000/sync-calendar to fetch events

You should now see meetings populate in the dashboard!

⸻

🧪 Development Notes
- DB path is explicitly set in app.py to avoid issues with multiple instances
- meetings.db is stored in a fixed location 
- Dates are handled as datetime.date for consistent filtering

⸻

📦 Deployment

You can deploy this app to:
- Render (sample https://meeting-tracker-rw96.onrender.com/)
- Railway
- Fly.io

Be sure to add your credentials.json and token file securely or use secrets storage.

⸻

📌 TODO
- Fix Google Calendar sync issue with time filtering
- Add recurring sync scheduler (e.g., daily)
- Export to CSV
- Mobile-friendly UI

⸻


