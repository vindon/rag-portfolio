"""
05-it-helpdesk-agent/tools/google_calendar.py

Google Calendar integration for scheduling technician visits.

Behaviour:
  - If credentials.json exists → real OAuth2 Google Calendar API
  - Otherwise → mock/demo mode that simulates scheduling (app still works)

Setup (real Calendar):
  1. Go to https://console.cloud.google.com
  2. Create project → Enable Google Calendar API
  3. Credentials → OAuth 2.0 Client ID → Desktop app
  4. Download as credentials.json into 05-it-helpdesk-agent/
  5. First run triggers browser-based OAuth consent
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from shared.config import config

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
CALENDAR_ID = "primary"


class CalendarTool:
    """
    Creates Google Calendar appointments for IT technician visits.
    Automatically falls back to mock mode when credentials aren't configured.
    """

    def __init__(self) -> None:
        self._service = None
        self._mock_mode = True
        self._try_connect()

    def _try_connect(self) -> None:
        creds_path = Path(config.google_credentials_path)
        token_path = Path(config.google_token_path)

        if not creds_path.exists():
            logger.info(
                "Google Calendar: credentials.json not found — running in demo mode. "
                "See tools/google_calendar.py for setup instructions."
            )
            return  # remain in mock mode

        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build

            creds = None
            if token_path.exists():
                creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(creds_path), SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                with open(token_path, "w") as f:
                    f.write(creds.to_json())

            self._service = build("calendar", "v3", credentials=creds)
            self._mock_mode = False
            logger.info("Google Calendar API connected ✓")

        except ImportError:
            logger.warning(
                "Google API packages not installed. "
                "Run: pip install google-api-python-client google-auth-oauthlib"
            )
        except Exception as e:
            logger.warning("Google Calendar connection failed: %s — using mock mode", e)

    def schedule_appointment(
        self,
        title: str,
        description: str,
        days_from_now: int = 1,
        hour: int = 10,
    ) -> Dict:
        """
        Schedule a technician visit.
        Returns event metadata dict (real or simulated).
        """
        start_dt = datetime.now().replace(
            hour=hour, minute=0, second=0, microsecond=0
        ) + timedelta(days=days_from_now)
        end_dt = start_dt + timedelta(hours=1)

        if self._mock_mode:
            return self._mock_event(title, description, start_dt, end_dt)
        return self._real_event(title, description, start_dt, end_dt)

    def _real_event(
        self, title: str, description: str, start: datetime, end: datetime
    ) -> Dict:
        event_body = {
            "summary": title,
            "description": description,
            "location": "IT Hub — Floor 3, Desk 34",
            "start": {"dateTime": start.isoformat(), "timeZone": "Asia/Kolkata"},
            "end":   {"dateTime": end.isoformat(),   "timeZone": "Asia/Kolkata"},
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email",  "minutes": 24 * 60},
                    {"method": "popup",  "minutes": 30},
                ],
            },
        }
        event = self._service.events().insert(
            calendarId=CALENDAR_ID, body=event_body
        ).execute()

        logger.info("Calendar event created: %s", event.get("htmlLink"))
        return {
            "event_id":  event.get("id"),
            "title":     title,
            "date":      start.strftime("%A, %d %B %Y"),
            "time":      start.strftime("%I:%M %p"),
            "location":  "IT Hub — Floor 3, Desk 34",
            "link":      event.get("htmlLink", ""),
            "note":      "Please bring your device. A calendar invite has been sent to your email.",
            "mock":      False,
        }

    def _mock_event(
        self, title: str, description: str, start: datetime, end: datetime
    ) -> Dict:
        """Simulated event — identical structure, no real API call."""
        logger.info("Mock Calendar: simulating event '%s' on %s", title, start.date())
        return {
            "event_id":  f"mock_{start.strftime('%Y%m%d%H%M')}",
            "title":     title,
            "date":      start.strftime("%A, %d %B %Y"),
            "time":      start.strftime("%I:%M %p"),
            "location":  "IT Hub — Floor 3, Desk 34",
            "link":      "https://calendar.google.com (demo mode)",
            "note":      (
                "Demo mode — no real calendar event created. "
                "Add credentials.json to enable real scheduling."
            ),
            "mock":      True,
        }
