"""
05-it-helpdesk-agent/graph.py

LangGraph StateGraph definition for the IT Helpdesk multi-agent system.

Graph topology:
  START
    └─► supervisor ──┬─► rag_agent    ──► supervisor (loop)
                     ├─► search_agent ──► supervisor (loop)
                     ├─► tools_agent  ──► END
                     └─► END (resolved)

The supervisor runs after every agent response to decide:
  - Route to another agent for more information, OR
  - Terminate (FINISH) when the issue is resolved

Concepts demonstrated:
  - LangGraph StateGraph with TypedDict state
  - Conditional edges (supervisor_router)
  - Multi-agent collaboration through shared state
  - Supervisor pattern (central routing LLM)
"""

import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.graph import StateGraph, START, END

from agents.state import HelpdeskState
from agents.supervisor import supervisor_node
from agents.rag_agent import rag_agent_node
from agents.search_agent import search_agent_node
from agents.calendar_agent import calendar_agent_node

logger = logging.getLogger(__name__)

# ── Node names ─────────────────────────────────────────────────────────────────
SUPERVISOR    = "supervisor"
RAG_AGENT     = "rag_agent"
SEARCH_AGENT  = "search_agent"
TOOLS_AGENT   = "tools_agent"


def supervisor_router(state: HelpdeskState) -> str:
    """
    Conditional edge: reads state['next_agent'] set by the supervisor node
    and routes to the corresponding node, or END if resolved.
    """
    if state.get("resolved"):
        logger.info("Graph: issue resolved → END")
        return END

    next_agent = state.get("next_agent", SUPERVISOR)
    logger.info("Graph: routing to → %s", next_agent)

    routing = {
        "rag_agent":    RAG_AGENT,
        "search_agent": SEARCH_AGENT,
        "tools_agent":  TOOLS_AGENT,
        "FINISH":       END,
    }
    return routing.get(next_agent, END)


def build_graph() -> StateGraph:
    """
    Assemble and compile the LangGraph StateGraph.
    Returns a compiled graph ready to invoke.
    """
    builder = StateGraph(HelpdeskState)

    # ── Register nodes ──────────────────────────────────────────────────────────
    builder.add_node(SUPERVISOR,   supervisor_node)
    builder.add_node(RAG_AGENT,    rag_agent_node)
    builder.add_node(SEARCH_AGENT, search_agent_node)
    builder.add_node(TOOLS_AGENT,  calendar_agent_node)

    # ── Edges ───────────────────────────────────────────────────────────────────
    # Entry point: always start at supervisor
    builder.add_edge(START, SUPERVISOR)

    # Supervisor decides where to go next (conditional)
    builder.add_conditional_edges(
        SUPERVISOR,
        supervisor_router,
        {
            RAG_AGENT:    RAG_AGENT,
            SEARCH_AGENT: SEARCH_AGENT,
            TOOLS_AGENT:  TOOLS_AGENT,
            END:          END,
        },
    )

    # After each specialist agent → back to supervisor to reassess
    builder.add_edge(RAG_AGENT,    SUPERVISOR)
    builder.add_edge(SEARCH_AGENT, SUPERVISOR)

    # Tools agent always terminates (ticket + calendar is the final action)
    builder.add_edge(TOOLS_AGENT, END)

    graph = builder.compile()
    logger.info("LangGraph compiled — nodes: %s", list(builder.nodes))
    return graph


# Singleton compiled graph
_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
