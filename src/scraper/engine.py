import asyncio
import logging
import random
from typing import Self

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
)
from playwright_stealth import Stealth

logger: logging.Logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_MS: int = 15_000
_MAX_RETRIES: int = 3
_BACKOFF_BASE: int = 2
_JITTER_MIN: float = 1.5
_JITTER_MAX: float = 4.0


class AsyncStealthBrowser:
    """Async context manager providing a stealth-hardened headless Chromium browser."""

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._stealth: Stealth = Stealth()

    async def __aenter__(self) -> Self:
        logger.info("Launching stealth browser")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context()
        self._page = await self._context.new_page()

        # Inject stealth evasions BEFORE any navigation
        await self._stealth.apply_stealth_async(self._page)

        # Block images, media, fonts, and stylesheets — cuts load time significantly
        await self._page.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in {"image", "media", "font", "stylesheet"}
            else route.continue_(),
        )

        self._page.set_default_navigation_timeout(_DEFAULT_TIMEOUT_MS)
        return self

    async def fetch_html(self, url: str) -> str:
        """Navigate to url and return raw page HTML.

        Applies a randomized jitter delay before navigation to avoid rate-limiting,
        then retries up to _MAX_RETRIES times with exponential backoff on network
        or timeout errors.
        """
        assert self._page is not None, "Browser not initialised — use as async context manager"

        last_exception: PlaywrightError | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            # Jitter before each navigation attempt to simulate human pacing
            jitter: float = random.uniform(_JITTER_MIN, _JITTER_MAX)
            logger.debug("Jitter delay %.2fs before attempt %d/%d", jitter, attempt, _MAX_RETRIES)
            await asyncio.sleep(jitter)

            try:
                logger.info("Fetching %s (attempt %d/%d)", url, attempt, _MAX_RETRIES)
                await self._page.goto(url, wait_until="networkidle")
                html: str = await self._page.content()
                logger.info("Fetched %s — %d chars", url, len(html))
                return html

            except PlaywrightTimeoutError as exc:
                last_exception = exc
                logger.warning(
                    "Timeout on %s (attempt %d/%d)",
                    url, attempt, _MAX_RETRIES,
                )
            except PlaywrightError as exc:
                last_exception = exc
                logger.warning(
                    "Network error on %s (attempt %d/%d): %s",
                    url, attempt, _MAX_RETRIES, exc,
                )

            if attempt < _MAX_RETRIES:
                backoff: float = float(_BACKOFF_BASE ** attempt)
                logger.info("Retrying in %.1fs...", backoff)
                await asyncio.sleep(backoff)

        logger.error("All %d attempts to fetch %s failed", _MAX_RETRIES, url)
        raise last_exception  # type: ignore[misc]  # guaranteed non-None after loop

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        logger.info("Shutting down stealth browser")
        if self._page:
            await self._page.close()
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
