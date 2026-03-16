import logging
import re

from bs4 import BeautifulSoup, Tag
from markdownify import MarkdownConverter

logger: logging.Logger = logging.getLogger(__name__)

_STRIP_TAGS: tuple[str, ...] = (
    "header", "footer", "aside", "form", "nav",
    "script", "style", "noscript", "iframe", "svg",
)

# Word-boundary-safe pattern — matches only when the keyword is delimited by
# start/end of string, hyphens, underscores, or whitespace.
# Prevents false positives on words like "shadow", "heading", "thread", "download", "breadcrumb".
_JUNK_PATTERN: re.Pattern[str] = re.compile(
    r"(?:^|[-_\s])(?:ad|menu|banner|cookie|popup|modal|sidebar)(?:[-_\s]|$)",
    re.IGNORECASE,
)

_DEFAULT_CHUNK_MAX: int = 10_000


def parse_html_to_markdown(html_content: str) -> str:
    """Sanitize raw HTML and convert to token-efficient Markdown.

    Isolation priority: <article> → <body> → "" (empty string on failure).
    Strips structural noise tags, decomposes junk elements by class/id pattern,
    then converts the surviving tree to Markdown via markdownify.

    Returns an empty string on parse failure or missing content root, allowing
    callers to detect failure without processing a sentinel string.
    """
    try:
        soup = BeautifulSoup(html_content, "html.parser")

        # --- DOM isolation ---
        root: Tag | None = soup.find("article")  # type: ignore[assignment]
        if root is None:
            root = soup.find("body")  # type: ignore[assignment]
        if root is None:
            logger.debug("No <article> or <body> found — returning empty string")
            return ""

        # --- Structural tag stripping ---
        for tag in list(root.find_all(_STRIP_TAGS)):
            tag.decompose()

        # --- Attribute-based junk removal (class and id) ---
        # list() copy is required — decompose() mutates the tree in-place
        for tag in list(root.find_all(attrs={"class": _JUNK_PATTERN})):
            tag.decompose()
        for tag in list(root.find_all(attrs={"id": _JUNK_PATTERN})):
            tag.decompose()

        # --- Markdown conversion ---
        # convert_soup() accepts a pre-parsed Tag, avoiding redundant re-parsing.
        # strip=['img'] drops images for maximum token efficiency.
        # heading_style='atx' produces clean # / ## / ### headers.
        markdown: str = MarkdownConverter(
            strip=["img"],
            heading_style="atx",
        ).convert_soup(root)

        return markdown.strip()

    except Exception as exc:  # noqa: BLE001
        logger.error("parse_html_to_markdown failed: %s", exc, exc_info=True)
        return ""


def chunk_markdown(text: str, max_chars: int = _DEFAULT_CHUNK_MAX) -> list[str]:
    """Split a Markdown string into chunks of at most max_chars characters.

    Splits on double-newlines (paragraph boundaries) to preserve Markdown
    structure. If a single paragraph exceeds max_chars, it is hard-split at
    the character limit.

    Returns a list of strings. If text fits within max_chars, returns a
    single-element list.
    """
    if len(text) <= max_chars:
        return [text]

    paragraphs: list[str] = text.split("\n\n")
    chunks: list[str] = []
    current: str = ""

    for paragraph in paragraphs:
        # Hard-split oversized individual paragraphs
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(paragraph), max_chars):
                chunks.append(paragraph[i : i + max_chars])
            continue

        candidate: str = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) > max_chars:
            chunks.append(current)
            current = paragraph
        else:
            current = candidate

    if current:
        chunks.append(current)

    return chunks
