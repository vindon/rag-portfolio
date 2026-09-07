"""
05-it-helpdesk-agent/agents/search_agent.py

Web Search Agent — searches DuckDuckGo for solutions not in the internal KB.
Free, no API key required.
"""

import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage

from shared.llm_factory import get_langchain_llm
from tools.web_search import DuckDuckGoSearchTool
from .state import HelpdeskState

logger = logging.getLogger(__name__)

SEARCH_SYSTEM = """You are an IT support specialist who has just conducted a web search.
Based on the search results below, provide a clear, practical solution to the employee's IT issue.

Guidelines:
- Synthesise information from multiple results into one coherent answer
- Prefer official documentation (Microsoft, Apple, vendor sites) over forums
- Give step-by-step instructions numbered clearly
- Mention any risks or prerequisites
- If the solution requires IT admin access, note it clearly
- Cite the source URL for the most useful result

Search results:
{results}

Employee issue: {question}

Provide the solution:"""


def search_agent_node(state: HelpdeskState) -> dict:
    """
    LangGraph node: search_agent.
    1. Extracts user query
    2. Searches DuckDuckGo (top 5 results)
    3. Synthesises with Groq
    4. Returns updated state
    """
    user_messages = [
        m for m in state["messages"]
        if hasattr(m, "type") and m.type == "human"
    ]
    query = user_messages[-1].content if user_messages else ""

    # Enrich query with category for better results
    category = state.get("category", "")
    search_query = f"IT support {category} fix: {query}" if category else f"IT support fix: {query}"
    logger.info("Search agent: %s", search_query[:80])

    # Step 1: Web search
    search_tool = DuckDuckGoSearchTool()
    results = search_tool.search(search_query, max_results=5)

    if not results:
        result_text = "No web search results found."
        trace = "🌐 Search Agent → No results"
    else:
        result_text = "\n\n".join(
            f"**{r['title']}** ({r['url']})\n{r['snippet']}"
            for r in results
        )
        trace = f"🌐 Search Agent → {len(results)} web results found"

    # Step 2: Synthesise
    llm = get_langchain_llm(temperature=0.1)
    messages = [
        SystemMessage(
            content=SEARCH_SYSTEM.format(results=result_text, question=query)
        ),
        HumanMessage(content=query),
    ]
    response = llm.invoke(messages)
    answer = response.content

    return {
        "messages": [AIMessage(content=f"**Web Search Results:**\n\n{answer}")],
        "context_docs": state.get("context_docs", []) + [result_text[:600]],
        "agent_trace": state.get("agent_trace", []) + [trace, "🌐 Search Agent → Synthesised answer"],
        "resolved": True,
    }
