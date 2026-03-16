import logging
import pathlib
from datetime import datetime

from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.scraper.engine import AsyncStealthBrowser
from src.scraper.parser import chunk_markdown, parse_html_to_markdown

logger: logging.Logger = logging.getLogger(__name__)

_LOGS_DIR: pathlib.Path = pathlib.Path(".logs")


def _save_debug_logs(url: str, html: str, markdown: str) -> None:
    """Write raw HTML and parsed Markdown to .logs/ for post-mortem debugging.

    Non-fatal — a write failure is logged as a warning and silently skipped
    so that the tool's primary return value is never affected.
    """
    try:
        _LOGS_DIR.mkdir(exist_ok=True)
        timestamp: str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        (_LOGS_DIR / f"raw_{timestamp}.html").write_text(html, encoding="utf-8")
        (_LOGS_DIR / f"parsed_{timestamp}.md").write_text(markdown, encoding="utf-8")
        logger.debug("Debug logs written to %s (prefix: %s)", _LOGS_DIR, timestamp)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to write debug logs for %s: %s", url, exc)


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------


class ScraperInput(BaseModel):
    url: str = Field(
        description=(
            "The fully-qualified URL of the webpage to scrape "
            "(e.g. https://example.com/article). Must include the scheme (https://)."
        )
    )


class SearchInput(BaseModel):
    query: str = Field(
        description=(
            "The natural-language search query used to find relevant web pages "
            "(e.g. 'Python asyncio best practices 2024'). "
            "Returns a summary of top results with URLs."
        )
    )


# ---------------------------------------------------------------------------
# Tool 1 — scrape_webpage
# ---------------------------------------------------------------------------


@tool(args_schema=ScraperInput)
async def scrape_webpage(url: str) -> str:
    """Fetch a webpage and return its content as clean, token-efficient Markdown.

    This tool launches a stealth-hardened headless Chromium browser that injects
    anti-fingerprinting scripts before any navigation, defeating most bot-detection
    systems (including basic Cloudflare challenges). It waits for the page to reach
    network-idle so that JavaScript-rendered SPA content is fully loaded before
    extraction.

    The raw HTML is then aggressively sanitized: structural noise tags (nav, header,
    footer, aside, scripts, ads, modals, sidebars) are removed, and the surviving
    content tree is converted to Markdown. Images are stripped for token efficiency.

    Use this tool when you have a specific URL you want to read in full. If you need
    to find URLs first, use the `search_web` tool.

    Returns Markdown text. If the page is very long, only the first chunk is returned
    with a system note indicating how many additional chunks exist. Returns an error
    string (not an exception) on failure so the agent can decide to try a different URL.
    """
    try:
        async with AsyncStealthBrowser() as browser:
            html: str = await browser.fetch_html(url)

        markdown: str = parse_html_to_markdown(html)
        _save_debug_logs(url, html, markdown)

        if not markdown:
            logger.warning("No extractable content at %s", url)
            return f"No extractable content found at {url}"

        # Hard token-budget cap: 3,000 chars keeps each source well under
        # Groq's TPM limits while preserving the article's core content.
        if len(markdown) > 3000:
            markdown = markdown[:3000] + "... [TRUNCATED]"
            logger.debug("scrape_webpage: content truncated to 3000 chars for %s", url)

        return markdown

    except Exception as exc:  # noqa: BLE001
        logger.error("scrape_webpage failed for %s: %s", url, exc, exc_info=True)
        return f"Error: Failed to retrieve or parse URL {url}. Reason: {exc}"


# ---------------------------------------------------------------------------
# Tool 2 — search_web
# ---------------------------------------------------------------------------


@tool(args_schema=SearchInput)
async def search_web(query: str) -> str:
    """Search the web via DuckDuckGo and return a summary of the top results.

    Use this tool when you need to discover URLs or find pages relevant to a
    research topic before scraping them. Returns a plain-text summary of the
    top search results, including snippets and URLs that you can subsequently
    pass to the `scrape_webpage` tool for full content extraction.

    Requires no API key. Results are from DuckDuckGo's organic search index.

    Returns an error string (not an exception) on failure so the agent can
    rephrase the query or fall back to a different approach.
    """
    try:
        ddg: DuckDuckGoSearchRun = DuckDuckGoSearchRun()
        result: str = await ddg.ainvoke(query)
        logger.info("search_web('%s') returned %d chars", query, len(result))
        return result
    except Exception as exc:  # noqa: BLE001
        logger.error("search_web failed for query '%s': %s", query, exc, exc_info=True)
        return f"Error: Search failed for query '{query}'. Reason: {exc}"
