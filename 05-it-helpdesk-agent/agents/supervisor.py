"""
05-it-helpdesk-agent/agents/supervisor.py

Supervisor agent — routes each user request to the appropriate specialist agent.

Routing logic:
  - KB search available → try RAG agent first
  - Not found in KB / complex issue → web search agent
  - Issue requires ticket + scheduling → tools agent
  - Issue resolved → END
"""

import sys
import json
import logging
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from shared.llm_factory import get_langchain_llm
from .state import HelpdeskState

logger = logging.getLogger(__name__)

SUPERVISOR_SYSTEM = """You are the supervisor of an IT helpdesk multi-agent system.
Your job is to analyse the employee's IT support request and route it to the correct agent.

Available agents:
- rag_agent:    Searches the internal IT knowledge base. Use for standard IT issues (password reset, VPN, software install, network).
- search_agent: Searches the web for solutions not in the KB. Use for unusual errors, third-party software, or when RAG agent found nothing useful.
- tools_agent:  Creates IT support tickets and optionally schedules a technician visit. Use when the issue needs formal tracking or an on-site visit.
- FINISH:       The issue has been resolved. Use when you have a complete, actionable answer.

Review the conversation history and the context_docs gathered so far.
Output ONLY a JSON object with:
  - "next": one of ["rag_agent", "search_agent", "tools_agent", "FINISH"]
  - "reasoning": one sentence explaining the routing decision
  - "category": one of ["password", "vpn", "software", "hardware", "network", "other"]
  - "priority": one of ["P1", "P2", "P3", "P4"]

Priority guide:
  P1 = Security breach, total system failure
  P2 = Can't work at all (locked out, no VPN)
  P3 = Degraded function (software issue, slow performance)
  P4 = Question, minor issue, enhancement

Do NOT output anything except the JSON object."""


class RoutingDecision(BaseModel):
    next: Literal["rag_agent", "search_agent", "tools_agent", "FINISH"]
    reasoning: str = Field(description="One sentence explaining the routing")
    category: Literal["password", "vpn", "software", "hardware", "network", "other"]
    priority: Literal["P1", "P2", "P3", "P4"]


def supervisor_node(state: HelpdeskState) -> dict:
    """
    LangGraph node: supervisor.
    Reads conversation history + gathered context, decides the next agent.
    """
    llm = get_langchain_llm(temperature=0)
    structured_llm = llm.with_structured_output(RoutingDecision)

    # Build context summary for the supervisor
    context_summary = ""
    if state.get("context_docs"):
        context_summary = (
            f"\nContext already gathered by agents ({len(state['context_docs'])} docs):\n"
            + "\n---\n".join(state["context_docs"][:3])
        )

    messages = [
        SystemMessage(content=SUPERVISOR_SYSTEM + context_summary),
        *state["messages"],
    ]

    logger.info("Supervisor routing — %d messages in context", len(state["messages"]))

    try:
        decision = structured_llm.invoke(messages)
    except Exception as e:
        logger.error("Supervisor structured output failed: %s — defaulting to rag_agent", e)
        decision = RoutingDecision(
            next="rag_agent",
            reasoning="Fallback: defaulting to RAG search",
            category="other",
            priority="P3",
        )

    trace_entry = (
        f"🧭 Supervisor → **{decision.next}** | "
        f"{decision.category.upper()} | {decision.priority} | "
        f"_{decision.reasoning}_"
    )
    logger.info("Routing: %s", trace_entry)

    return {
        "next_agent": decision.next,
        "category": decision.category,
        "priority": decision.priority,
        "resolved": decision.next == "FINISH",
        "agent_trace": state.get("agent_trace", []) + [trace_entry],
    }
