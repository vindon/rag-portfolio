"""
05-it-helpdesk-agent/agents/state.py

LangGraph state schema for the IT Helpdesk multi-agent system.
All agents read from and write to this shared state object.
"""

from typing import Annotated, TypedDict, Optional
from langgraph.graph.message import add_messages


class HelpdeskState(TypedDict):
    """
    Shared state flowing through the LangGraph agent graph.

    LangGraph merges state updates from each node:
      - messages: accumulated using add_messages (append-only)
      - All other fields: last-write-wins
    """

    # Conversation messages (HumanMessage, AIMessage, ToolMessage)
    messages: Annotated[list, add_messages]

    # Routing and resolution
    next_agent: Optional[str]     # which node the supervisor routes to next
    resolved: bool                # True → graph terminates

    # IT ticket
    ticket_id:    Optional[str]   # SQLite ticket ID once created
    ticket_title: Optional[str]
    priority:     Optional[str]   # P1/P2/P3/P4

    # Category (helps supervisor route correctly)
    category: Optional[str]       # password | vpn | software | hardware | network | other

    # Context gathered by agents (appended by each agent, not replaced)
    context_docs: list[str]       # KB chunks from Weaviate RAG agent

    # Agent execution trace (for Streamlit display)
    agent_trace: list[str]        # ["Supervisor → RAG Agent", "RAG Agent → found 3 docs", ...]

    # Calendar
    calendar_event: Optional[dict]  # set if a tech visit is scheduled
