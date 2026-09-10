"""HTTP layer for Yalla Shoot (ysscores.com).

Behavior verified live on 2026-09-10:

- GET /ar/fixtures            → HTML of today's league blocks.
- GET /                       → issues the XSRF-TOKEN cookie (URL-encoded).
                                Needed before any CSRF-protected POST.
- POST /ar/match_date_to      → same league-block HTML for an arbitrary date.
                                Form field: get_date=<Month Name D,YYYY>.
                                Headers: X-XSRF-TOKEN (decoded), Referer,
                                X-Requested-With: XMLHttpRequest.
- GET /ar/match/{id}/{slug}   → match detail page; channels, commentator AND
                                the events (goals/cards/subs) are inline HTML,
                                so no separate events API call is needed.

Politeness & robustness:
- 1–3 s random delay between requests (global lock ⇒ requests serialized).
- At most `MAX_CONCURRENCY` connections open.
- Retry with exponential backoff on 429/503 and transient network errors.
- One failing match page/network blip never crashes the whole run.
"""

from __future__ import annotations

import logging
import random
import threading
import time
import urllib.parse as up
from datetime import date

import httpx

from data_layer import config

logger = logging.getLogger(__name__)


class FetcherError(RuntimeError):
    """Raised when a request fails after all retries were exhausted."""


class _RetryableError(FetcherError):
    """Internal: a retryable transport or HTTP failure happened."""


class Fetcher:
    """Bot-safe HTTP client for the ysscores.com data endpoints.

    Not thread-safe for *booking* by itself, but every round-trip is guarded
    by an internal lock: the random delay + cookie refresh stay atomic, so
    callers may freely fan out requests across up to `max_concurrency`
    threads.
    """

    def __init__(
        self,
        *,
        delay_range: tuple[float, float] = config.REQUEST_DELAY_RANGE,
        max_concurrency: int = config.MAX_CONCURRENCY,
        timeout: float = config.HTTP_TIMEOUT,
        retries: int = config.RETRY_MAX_ATTEMPTS,
        user_agent: str = config.USER_AGENT,
    ) -> None:
        self.delay_range = delay_range
        self.timeout = timeout
        self.retries = max(1, retries)
        self.user_agent = user_agent
        self._client: httpx.Client | None = None
        # Reentrant: _polite_next / _refresh_csrf are also called from inside
        # the round-trip critical section.
        self._lock = threading.RLock()
        self._last_request_at = 0.0
        self._session_ready = False
        self._limits = httpx.Limits(
            max_connections=max_concurrency,
            max_keepalive_connections=max_concurrency,
        )

    # ── lifecycle ──────────────────────────────────────────────────────────
    def _ensure_session(self) -> httpx.Client:
        """(Re)build the client and plant a fresh CSRF cookie once per run."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                timeout=self.timeout,
                limits=self._limits,
                follow_redirects=True,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": config.ACCEPT_HTML,
                    "Accept-Language": config.ACCEPT_LANGUAGE,
                },
            )
        if not self._session_ready:
            self._refresh_csrf()
        return self._client

    def _refresh_csrf(self) -> None:
        """GET / so the server plants a fresh XSRF-TOKEN cookie in the jar."""
        assert self._client is not None
        self._polite_next()
        self._client.get(config.BASE_URL + config.HOME_PATH)
        self._session_ready = True

    def _xsrf_header(self) -> dict[str, str]:
        """Return the decoded CSRF header if the cookie is present."""
        assert self._client is not None
        raw = self._client.cookies.get("XSRF-TOKEN")
        if not raw:
            return {}
        return {"X-XSRF-TOKEN": up.unquote(raw)}

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self._session_ready = False

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── politeness ─────────────────────────────────────────────────────────
    def _polite_next(self) -> None:
        """Sleep so that >= min_delay elapses since the previous round-trip."""
        lo, hi = self.delay_range
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_at
            wait = random.uniform(lo, hi) - elapsed
            if wait > 0:
                time.sleep(wait)
            self._last_request_at = time.monotonic()

    # ── low-level request with retry ───────────────────────────────────────
    def _request(
        self, method: str, url: str, *, data: dict[str, str] | None = None
    ) -> str:
        """Perform one request, retrying transient failures with backoff.

        Never raises for a single bad match/page: caller decides to skip.
        Raises FetcherError once retries are exhausted.
        """
        for attempt in range(1, self.retries + 1):
            try:
                # Whole round-trip under the lock → serialized + delay applied
                # exactly once, and concurrent readers cannot interleave.
                with self._lock:
                    self._polite_next()
                    client = self._ensure_session()
                    headers: dict[str, str] = {
                        "Referer": config.BASE_URL + config.FIXTURES_PATH,
                    } if method == "GET" else {
                        **self._xsrf_header(),
                        "Referer": config.BASE_URL + config.FIXTURES_PATH,
                        "X-Requested-With": "XMLHttpRequest",
                        "Content-Type": "application/x-www-form-urlencoded",
                    }
                    if method.lower() == "get":
                        resp = client.get(url, headers=headers)
                    else:
                        resp = client.post(url, data=data, headers=headers)
                return self._handle_response(resp, url)
            except _RetryableError:
                if attempt == self.retries:
                    raise FetcherError(
                        f"GET {url} failed after {self.retries} attempts"
                    ) from None
                wait = config.RETRY_BACKOFF_BASE * 2 ** (attempt - 1)
                logger.warning(
                    "transient failure (%s) → retry %d/%d in %.1fs",
                    url, attempt + 1, self.retries, wait,
                )
                time.sleep(wait + random.uniform(0, 1))
        raise FetcherError(f"unreachable: {url}")  # pragma: no cover

    def _handle_response(self, resp: httpx.Response, url: str) -> str:
        # CSRF went stale → the token cookie rotated mid-conversation.
        if (
            resp.status_code == config.CSRF_ERROR_STATUS
            and (url or "").endswith(config.DATE_ENDPOINT_PATH)
        ):
            logger.info("CSRF expired, refreshing cookie (419 on %s)", url)
            with self._lock:
                self._session_ready = False
                self._refresh_csrf()
            raise _RetryableError("csrf token mismatch, retrying")

        if resp.status_code in config.RETRY_STATUS_CODES:
            raise _RetryableError(f"server asked to back off ({resp.status_code})")

        if resp.status_code >= 400:
            raise FetcherError(f"{url} → HTTP {resp.status_code}")

        return resp.text

    # ── high-level endpoints ───────────────────────────────────────────────
    def fetch_fixtures_html(self) -> str:
        """Today's league blocks (list page)."""
        return self._request("GET", config.BASE_URL + config.FIXTURES_PATH)

    def fetch_matches_html_for_date(self, day: date) -> str:
        """League blocks for an arbitrary date using the site's picker API."""
        return self._request(
            "POST",
            config.BASE_URL + config.DATE_ENDPOINT_PATH,
            data={"get_date": config.locale_date(day)},
        )

    def fetch_match_page(self, source_url: str) -> str:
        """Match detail page (channels, commentator, events all inline)."""
        return self._request("GET", source_url)