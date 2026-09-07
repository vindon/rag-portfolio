"""
05-it-helpdesk-agent/app.py

IT Helpdesk Multi-Agent System — Streamlit application.

Run:
    cd 05-it-helpdesk-agent
    streamlit run app.py

Features:
  - LangGraph multi-agent with supervisor routing
  - Real-time agent execution trace panel
  - Weaviate KB search + DuckDuckGo web search
  - SQLite ticket creation with auto-ID
  - Google Calendar scheduling (real or mock)
  - Ticket history dashboard
"""

import sys
import json
import logging
from pathlib import Path

import streamlit as st
from langchain_core.messages import HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph import get_graph
from agents.state import HelpdeskState
from tools.ticket_tracker import TicketTracker
from shared.utils import ollama_warning

logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="IT Helpdesk Agent",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  .trace-box {
    background: #0d1117;
    border: 1px solid #21262d;
    border-radius: 8px;
    padding: 1rem;
    font-family: monospace;
    font-size: 0.82rem;
    max-height: 400px;
    overflow-y: auto;
  }
  .agent-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 0.72rem;
    font-weight: 600;
    margin: 2px;
  }
  .badge-supervisor { background: #553c9a; color: #e9d8fd; }
  .badge-rag       { background: #2c7a7b; color: #b2f5ea; }
  .badge-search    { background: #744210; color: #fefcbf; }
  .badge-tools     { background: #276749; color: #c6f6d5; }
  .ticket-card {
    background: #1e2130;
    border-left: 3px solid #6C63FF;
    padding: 0.8rem 1rem;
    border-radius: 0 8px 8px 0;
    margin: 0.4rem 0;
    font-size: 0.85rem;
  }
  .p1 { border-left-color: #fc8181 !important; }
  .p2 { border-left-color: #f6ad55 !important; }
  .p3 { border-left-color: #68d391 !important; }
  .p4 { border-left-color: #718096 !important; }
</style>
""", unsafe_allow_html=True)

EXAMPLE_REQUESTS = [
    "I can't log in — my account seems locked after too many password attempts",
    "How do I set up VPN on my new MacBook?",
    "Slack keeps crashing on startup on my Mac. How do I fix it?",
    "I need a new monitor — my current one has a broken screen",
    "My Wi-Fi keeps disconnecting in the office on the 3rd floor",
    "How do I enroll in MFA using my new phone?",
    "Zoom audio isn't working during calls — my mic isn't detected",
    "I accidentally deleted an important file from SharePoint — can it be recovered?",
]


def init_session():
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "agent_trace" not in st.session_state:
        st.session_state.agent_trace = []
    if "tickets" not in st.session_state:
        st.session_state.tickets = []
    if "graph" not in st.session_state:
        with st.spinner("Initialising IT agent graph…"):
            st.session_state.graph = get_graph()


def render_sidebar():
    with st.sidebar:
        st.title("🤖 IT Helpdesk Agent")
        st.caption("LangGraph · Weaviate · Groq · SQLite")

        warn = ollama_warning()
        if warn:
            st.warning(warn, icon="⚠️")

        st.divider()
        st.subheader("🏗️ Agent Architecture")
        st.markdown("""
        ```
        User Request
             │
          Supervisor (Groq LLM)
         ╱    │        ╲
        ▼     ▼         ▼
       RAG  Web      Tools
      Agent Search   Agent
        │   Agent      │
        │     │    Ticket +
        └──►Supervisor Calendar
                │
               END
        ```
        """)

        st.divider()
        st.subheader("🎫 Ticket History")
        tracker = TicketTracker()
        tickets = tracker.list_tickets(limit=10)
        if not tickets:
            st.caption("No tickets yet")
        else:
            for t in tickets:
                p_class = t["priority"].lower()
                st.markdown(
                    f'<div class="ticket-card {p_class}">'
                    f'<strong>{t["id"]}</strong> — {t["priority"]}<br>'
                    f'<small>{t["title"][:50]}</small><br>'
                    f'<span style="color:#718096;font-size:0.7rem">'
                    f'{t["status"].upper()} · {t["created_at"][:10]}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        st.divider()
        if st.button("🗑️ Clear Chat"):
            st.session_state.messages = []
            st.session_state.agent_trace = []
            st.rerun()


def render_trace(trace: list):
    """Render the agent execution trace in the right column."""
    if not trace:
        st.caption("Agent trace will appear here during processing…")
        return
    trace_html = "<br>".join(
        f"<span style='color:#a0aec0'>{entry}</span>"
        for entry in trace
    )
    st.markdown(
        f'<div class="trace-box">{trace_html}</div>',
        unsafe_allow_html=True,
    )


def run_agent(user_input: str) -> dict:
    """Invoke the LangGraph graph and return the final state."""
    graph = st.session_state.graph

    initial_state: HelpdeskState = {
        "messages":      [HumanMessage(content=user_input)],
        "next_agent":    None,
        "resolved":      False,
        "ticket_id":     None,
        "ticket_title":  None,
        "priority":      None,
        "category":      None,
        "context_docs":  [],
        "agent_trace":   [],
        "calendar_event": None,
    }

    final_state = graph.invoke(
        initial_state,
        config={"recursion_limit": 10},
    )
    return final_state


def main():
    init_session()
    render_sidebar()

    st.title("🤖 IT Helpdesk Multi-Agent System")
    st.caption(
        "LangGraph supervisor · Weaviate RAG · DuckDuckGo search · "
        "SQLite tickets · Google Calendar"
    )

    # ── Layout: chat left, trace right ────────────────────────────────────────
    col_chat, col_trace = st.columns([2, 1])

    with col_chat:
        # Example requests
        if not st.session_state.messages:
            st.markdown("#### 💡 Common IT requests")
            cols = st.columns(2)
            for i, example in enumerate(EXAMPLE_REQUESTS[:6]):
                with cols[i % 2]:
                    if st.button(example, key=f"ex_{i}", use_container_width=True):
                        st.session_state._pending_input = example
                        st.rerun()

        # Chat history
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg.get("ticket_id"):
                    st.info(f"🎫 Ticket: **{msg['ticket_id']}**")
                if msg.get("calendar_event"):
                    ev = msg["calendar_event"]
                    st.success(
                        f"📅 Visit scheduled: **{ev['date']}** at {ev['time']} — {ev['location']}"
                    )

        # Handle pre-filled input from example buttons
        prefill = st.session_state.pop("_pending_input", "")

        # Chat input
        user_input = st.chat_input(
            "Describe your IT issue…",
            value=prefill if prefill else None,
        ) or prefill

        if user_input:
            # Show user message immediately
            st.session_state.messages.append({
                "role": "user",
                "content": user_input,
            })
            with st.chat_message("user"):
                st.markdown(user_input)

            # Run agent
            with st.chat_message("assistant"):
                with st.spinner("Agents working…"):
                    final_state = run_agent(user_input)

                # Extract the last AI message
                ai_messages = [
                    m for m in final_state.get("messages", [])
                    if hasattr(m, "type") and m.type == "ai"
                ]
                answer = ai_messages[-1].content if ai_messages else "I was unable to process your request."
                st.markdown(answer)

                # Show ticket info inline
                ticket_id = final_state.get("ticket_id")
                if ticket_id:
                    st.info(f"🎫 Ticket created: **{ticket_id}**")

                # Show calendar event inline
                cal_event = final_state.get("calendar_event")
                if cal_event:
                    st.success(
                        f"📅 Technician visit: **{cal_event['date']}** at {cal_event['time']}"
                    )

            # Store in session
            st.session_state.messages.append({
                "role":           "assistant",
                "content":        answer,
                "ticket_id":      ticket_id,
                "calendar_event": cal_event,
            })
            st.session_state.agent_trace = final_state.get("agent_trace", [])
            st.rerun()

    with col_trace:
        st.subheader("🔍 Agent Execution Trace")
        render_trace(st.session_state.agent_trace)

        if st.session_state.agent_trace:
            st.divider()
            # Show metadata from last run
            tickets = TicketTracker().list_tickets(limit=1)
            if tickets:
                t = tickets[0]
                col_a, col_b = st.columns(2)
                col_a.metric("Category", t["category"].upper())
                col_b.metric("Priority", t["priority"])


if __name__ == "__main__":
    main()
