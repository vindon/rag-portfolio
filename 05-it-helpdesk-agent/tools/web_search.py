"""
05-it-helpdesk-agent/tools/web_search.py

DuckDuckGo web search tool — free, no API key, privacy-respecting.
Used by the Search Agent when the internal KB has no answer.
"""

import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class DuckDuckGoSearchTool:
    """
    Thin wrapper around duckduckgo-search for IT support queries.
    Returns structured result dicts: {title, url, snippet}.
    """

    def search(self, query: str, max_results: int = 5) -> List[Dict]:
        """
        Search DuckDuckGo and return top results.
        Falls back to empty list if the package is unavailable or rate-limited.
        """
        try:
            from duckduckgo_search import DDGS
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append({
                        "title":   r.get("title", ""),
                        "url":     r.get("href", ""),
                        "snippet": r.get("body", "")[:400],
                    })
            logger.info("DuckDuckGo returned %d results for: %s", len(results), query[:60])
            return results

        except ImportError:
            logger.error("duckduckgo-search not installed. Run: pip install duckduckgo-search")
            return []

        except Exception as e:
            logger.warning("DuckDuckGo search failed: %s", e)
            # Graceful fallback — return a canned helpful message
            return [{
                "title": "Search unavailable",
                "url": "https://support.microsoft.com",
                "snippet": (
                    f"Could not retrieve search results ({e}). "
                    "Try searching manually at support.microsoft.com or support.apple.com."
                ),
            }]
