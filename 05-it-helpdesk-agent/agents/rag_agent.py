"""
05-it-helpdesk-agent/agents/rag_agent.py

RAG Agent — searches the Weaviate IT knowledge base and composes an answer.
Uses Ollama for embeddings and Groq for synthesis.
"""

import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage

from shared.llm_factory import get_langchain_llm
from tools.weaviate_rag import WeaviateKBTool
from .state import HelpdeskState

logger = logging.getLogger(__name__)

RAG_SYSTEM = """You are an IT knowledge base specialist. You have retrieved the following
documentation excerpts relevant to the employee's issue.

Your job:
1. Synthesise a clear, step-by-step solution from the retrieved docs
2. Number each step
3. Highlight any prerequisites or cautions
4. If the docs don't fully address the issue, say what's missing and that a web search may help
5. Keep the answer concise — employees need to fix things quickly

Retrieved documentation:
{context}

Respond with the solution only. No preamble."""


def rag_agent_node(state: HelpdeskState) -> dict:
    """
    LangGraph node: rag_agent.
    1. Extracts the user's question from state
    2. Searches Weaviate KB via WeaviateKBTool
    3. Synthesises an answer with Groq
    4. Returns updated state
    """
    # Get the last user message as the search query
    user_messages = [
        m for m in state["messages"]
        if hasattr(m, "type") and m.type == "human"
    ]
    query = user_messages[-1].content if user_messages else ""

    logger.info("RAG agent searching KB for: %s", query[:80])

    # Step 1: Search Weaviate
    kb_tool = WeaviateKBTool()
    docs = kb_tool.search(query, top_k=4)

    trace_steps = []
    if not docs:
        context = "No relevant documentation found in the knowledge base."
        trace_steps.append("📚 RAG Agent → No KB results found")
    else:
        context = "\n\n---\n\n".join(
            f"[{d['source']}]\n{d['content']}" for d in docs
        )
        trace_steps.append(f"📚 RAG Agent → Found {len(docs)} KB chunks")

    # Step 2: Synthesise answer
    llm = get_langchain_llm(temperature=0.1)
    synthesis_messages = [
        SystemMessage(content=RAG_SYSTEM.format(context=context)),
        HumanMessage(content=query),
    ]
    response = llm.invoke(synthesis_messages)
    answer = response.content

    # Determine if this resolves the issue (heuristic: answer doesn't say "not found")
    resolved_keywords = ["unable to find", "not in the knowledge base", "web search may help"]
    found_answer = not any(kw in answer.lower() for kw in resolved_keywords)

    trace_steps.append(
        f"📚 RAG Agent → {'Resolved ✅' if found_answer else 'Partial — may need web search'}"
    )

    return {
        "messages": [AIMessage(content=f"**IT Knowledge Base:**\n\n{answer}")],
        "context_docs": state.get("context_docs", []) + [context[:800]],
        "agent_trace": state.get("agent_trace", []) + trace_steps,
        "resolved": found_answer,
    }
