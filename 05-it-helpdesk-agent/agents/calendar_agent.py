"""
05-it-helpdesk-agent/agents/calendar_agent.py

Tools Agent — creates IT support tickets (SQLite) and optionally
schedules technician calendar appointments (Google Calendar or mock).
"""

import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langchain_core.output_parsers import JsonOutputParser

from shared.llm_factory import get_langchain_llm
from tools.ticket_tracker import TicketTracker
from tools.google_calendar import CalendarTool
from .state import HelpdeskState

logger = logging.getLogger(__name__)

TICKET_EXTRACTION_SYSTEM = """Extract ticket details from this IT support conversation.

Return ONLY a JSON object with these fields:
- title: Short 5-10 word ticket title (string)
- description: Full issue description (string, 2-3 sentences)
- needs_visit: true if issue requires physical technician visit (bool)
- visit_reason: why a visit is needed, or "" if not needed (string)

Examples that need_visit=true: hardware damage, equipment replacement, network port issue, printer setup
Examples that need_visit=false: password reset, software install, VPN config, account access

Return only valid JSON, no preamble."""


def calendar_agent_node(state: HelpdeskState) -> dict:
    """
    LangGraph node: tools_agent.
    1. Extracts ticket details via LLM
    2. Creates SQLite ticket
    3. If physical visit needed → schedules Google Calendar appointment
    """
    user_messages = [
        m for m in state["messages"]
        if hasattr(m, "type") and m.type == "human"
    ]
    conversation = "\n".join(
        f"{'Employee' if m.type == 'human' else 'Support'}: {m.content}"
        for m in state["messages"][-6:]
    )

    # Step 1: Extract ticket details
    llm = get_langchain_llm(temperature=0)
    parser = JsonOutputParser()
    extraction_messages = [
        SystemMessage(content=TICKET_EXTRACTION_SYSTEM),
        HumanMessage(content=f"Conversation:\n{conversation}"),
    ]
    try:
        raw = llm.invoke(extraction_messages)
        ticket_info = parser.parse(raw.content)
    except Exception as e:
        logger.warning("Ticket extraction failed: %s — using defaults", e)
        ticket_info = {
            "title": "IT Support Request",
            "description": conversation[:200],
            "needs_visit": False,
            "visit_reason": "",
        }

    # Step 2: Create ticket
    tracker = TicketTracker()
    ticket = tracker.create_ticket(
        title=ticket_info.get("title", "IT Support Request"),
        description=ticket_info.get("description", ""),
        priority=state.get("priority", "P3"),
        category=state.get("category", "other"),
    )
    trace_entries = [f"🎫 Tools Agent → Ticket created: **{ticket['id']}** ({ticket['priority']})"]
    calendar_event = None

    # Step 3: Schedule visit if needed
    if ticket_info.get("needs_visit"):
        cal = CalendarTool()
        calendar_event = cal.schedule_appointment(
            title=f"IT Visit: {ticket_info['title']}",
            description=(
                f"Ticket: {ticket['id']}\n"
                f"Issue: {ticket_info['description']}\n"
                f"Reason: {ticket_info.get('visit_reason', '')}"
            ),
        )
        trace_entries.append(
            f"📅 Tools Agent → {'Calendar event created (mock mode)' if calendar_event.get('mock') else 'Calendar event scheduled'}: "
            f"**{calendar_event.get('date', 'TBD')}** at {calendar_event.get('time', 'TBD')}"
        )

    # Step 4: Compose confirmation message
    msg_parts = [
        f"**✅ Support Ticket Created**\n",
        f"- **Ticket ID:** `{ticket['id']}`",
        f"- **Priority:** {ticket['priority']}",
        f"- **Category:** {ticket['category'].upper()}",
        f"- **Status:** {ticket['status']}",
        f"- **SLA:** {_sla_text(ticket['priority'])}",
    ]

    if calendar_event:
        msg_parts += [
            f"\n**📅 Technician Visit Scheduled**",
            f"- **Date:** {calendar_event.get('date', 'Next available slot')}",
            f"- **Time:** {calendar_event.get('time', '10:00 AM')}",
            f"- **Location:** {calendar_event.get('location', 'IT Hub — Floor 3, Desk 34')}",
            f"- **Note:** {calendar_event.get('note', 'Please bring your device.')}",
        ]

    msg_parts.append(
        "\n\nYou will receive an email confirmation. "
        "Track your ticket at https://helpdesk.acmecorp.internal"
    )

    return {
        "messages": [AIMessage(content="\n".join(msg_parts))],
        "ticket_id": ticket["id"],
        "ticket_title": ticket["title"],
        "calendar_event": calendar_event,
        "agent_trace": state.get("agent_trace", []) + trace_entries,
        "resolved": True,
    }


def _sla_text(priority: str) -> str:
    return {
        "P1": "30 minutes (Critical)",
        "P2": "2 hours (High)",
        "P3": "8 hours (Normal)",
        "P4": "2 business days (Low)",
    }.get(priority, "8 hours")
