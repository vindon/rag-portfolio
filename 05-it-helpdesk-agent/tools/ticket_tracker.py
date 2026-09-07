"""
05-it-helpdesk-agent/tools/ticket_tracker.py

SQLite-backed IT support ticket system.
Zero dependencies beyond Python stdlib — no Docker, no external DB.

Schema:
  tickets(id, title, description, priority, category, status,
          created_at, updated_at, resolution)
"""

import sqlite3
import uuid
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = str(Path(__file__).parent.parent / "tickets.db")

PRIORITY_SLA = {
    "P1": "30 minutes",
    "P2": "2 hours",
    "P3": "8 hours",
    "P4": "2 business days",
}


class TicketTracker:
    """
    Simple IT support ticket CRUD using SQLite.

    In production this would integrate with ServiceNow, Jira Service Desk,
    or Freshservice. SQLite is used here to keep the portfolio dependency-free.
    """

    def __init__(self, db_path: str = DB_PATH) -> None:
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    id          TEXT PRIMARY KEY,
                    title       TEXT NOT NULL,
                    description TEXT,
                    priority    TEXT DEFAULT 'P3',
                    category    TEXT DEFAULT 'other',
                    status      TEXT DEFAULT 'open',
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL,
                    resolution  TEXT
                )
            """)
            conn.commit()
        logger.debug("Ticket DB initialised at %s", self.db_path)

    def create_ticket(
        self,
        title: str,
        description: str = "",
        priority: str = "P3",
        category: str = "other",
    ) -> Dict:
        """Create a new ticket and return its record as a dict."""
        ticket_id = f"INC-{uuid.uuid4().hex[:6].upper()}"
        now = datetime.utcnow().isoformat()
        priority = priority if priority in PRIORITY_SLA else "P3"

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tickets
                  (id, title, description, priority, category, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'open', ?, ?)
                """,
                (ticket_id, title[:120], description[:1000], priority, category, now, now),
            )
            conn.commit()

        logger.info("Ticket created: %s | %s | %s", ticket_id, priority, title[:60])
        return {
            "id":          ticket_id,
            "title":       title,
            "priority":    priority,
            "category":    category,
            "status":      "open",
            "sla":         PRIORITY_SLA.get(priority, "8 hours"),
            "created_at":  now,
        }

    def get_ticket(self, ticket_id: str) -> Optional[Dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
            ).fetchone()
        return dict(row) if row else None

    def update_status(
        self,
        ticket_id: str,
        status: str,
        resolution: str = "",
    ) -> Dict:
        """Update ticket status. Valid statuses: open, in_progress, resolved, closed."""
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tickets
                   SET status = ?, resolution = ?, updated_at = ?
                 WHERE id = ?
                """,
                (status, resolution, now, ticket_id),
            )
            conn.commit()
        logger.info("Ticket %s → %s", ticket_id, status)
        return self.get_ticket(ticket_id) or {}

    def list_tickets(
        self,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict]:
        query = "SELECT * FROM tickets"
        params: list = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def ticket_count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
