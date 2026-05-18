"""
Search tools used by domain agents.

Design goals:
- open-source libraries
- no paid API requirement
- internet access on Brev instance is enough
"""
import logging

logger = logging.getLogger(__name__)


def get_search_tool():
    """Return the primary web search tool (DuckDuckGo)."""
    try:
        from langchain_community.tools import DuckDuckGoSearchResults
        logger.info("Using DuckDuckGo search tool")
        return DuckDuckGoSearchResults(num_results=8, output_format="list")
    except Exception as exc:
        logger.error(f"Search tool unavailable: {exc}")
        return None
