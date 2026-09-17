#!/usr/bin/env python3
"""Check the footnotes of a document by loading every link it cites.

Version 1 is deterministic. It reports what it saw when it asked for each page.
It never judges whether a page supports the claim. That step comes later.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

TOOL_VERSION = "0.1"

EXIT_INPUT_ERROR = 2
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024
FETCH_THREADS = 8
DEFAULT_TIMEOUT_SECONDS = 15

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
ARCHIVE_USER_AGENT = "curl-my-footnotes/0.1 (footnote link checker; personal use)"

# The archive answers anonymous callers with 429 when they arrive in a burst,
# so every archive call is serialized and spaced out.
ARCHIVE_PAUSE_SECONDS = 1.5
ARCHIVE_BACKOFF_SECONDS = (5, 15, 30)
ARCHIVE_MAX_TRIES = 3
ARCHIVE_RETRY_STATUS = (429, 500, 502, 503, 504)
ARCHIVE_AVAILABILITY_ENDPOINT = "https://archive.org/wayback/available?url="
ARCHIVE_CDX_ENDPOINT = (
    "https://web.archive.org/cdx/search/cdx?url={url}&output=json"
    "&limit=-1&filter=statuscode:200&fl=timestamp,original"
)
# The plain form is the one a person clicks. The id_ form returns the saved page
# without the archive toolbar, which is what the page text should be taken from.
ARCHIVE_SNAPSHOT_TEMPLATE = "https://web.archive.org/web/{timestamp}/{original}"
ARCHIVE_RAW_SNAPSHOT_TEMPLATE = "https://web.archive.org/web/{timestamp}id_/{original}"
ARCHIVE_SNAPSHOT_PREFIX_RE = re.compile(r"^https?://web\.archive\.org/web/[^/]+/")

# Some Python builds ship with an empty certificate store, which would make every
# HTTPS link look broken. These are the bundles an operating system already keeps.
CERT_BUNDLE_CANDIDATES = (
    "/etc/ssl/cert.pem",
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/tls/certs/ca-bundle.crt",
)

SOFT_404_PATTERNS = (
    "404",
    "not found",
    "page not found",
    "page doesn't exist",
    "no longer available",
)
# A robot check answers with a normal status code, so the tool never saw the real
# page. That is an unclear answer, not proof that the page is gone.
BOT_WALL_PATTERNS = (
    "client challenge",
    "just a moment",
    "attention required",
    "access denied",
    "are you a robot",
    "verify you are human",
    "verifying you are human",
    "pardon our interruption",
    "security check",
    "captcha",
    "checking your browser",
)
MISSING_STATUS_CODES = (404, 410)
TEXT_CONTENT_HINTS = ("text/html", "application/xhtml", "text/plain", "text/markdown")

LABEL_LIVE = "live"
LABEL_DEAD_ARCHIVED = "dead, archived copy exists"
LABEL_NEVER_ARCHIVED = "does not load, never archived (possibly invented)"
LABEL_BLOCKED_ARCHIVED = "blocked live, archived copy exists"
LABEL_UNKNOWN = "could not check"
LABEL_NO_LINK = "not checked, no link"

ARCHIVE_FOUND = "found"
ARCHIVE_NOT_FOUND = "not_found"
ARCHIVE_LOOKUP_FAILED = "lookup_failed"
ARCHIVE_SKIPPED = "skipped"

INLINE_LINK_RE = re.compile(r"\[([^\]\n]*)\]\(([^)\s]+)\)")
FOOTNOTE_MARKER_RE = re.compile(r"\[\^([^\]\n]+)\](?!:)")
NUMBER_MARKER_RE = re.compile(r"\[(\d+)\](?![(:])")
BARE_URL_RE = re.compile(r"https?://[^\s<>\[\]\"']+")
FOOTNOTE_DEF_RE = re.compile(r"^\s*\[\^([^\]\n]+)\]:\s*(.*)$")
NUMBER_DEF_RE = re.compile(r"^\s*\[(\d+)\](?!\()\s*:?\s*(.*)$")
# A sentence ends at the full stop, after any markers glued to it, before the space.
SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])(?:\[\^[^\]\n]+\]|\[\d+\])*\s+")
SPACE_BEFORE_PUNCTUATION_RE = re.compile(r"\s+([.,;:!?])")
URL_IN_TEXT_RE = re.compile(r"https?://[^\s<>\[\]\"']+")
TRAILING_PUNCTUATION = ".,;:!?"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class Footnote:
    """One claim in the document plus the link that is supposed to back it up."""

    number: int
    marker: str
    line: int
    claim: str | None
    claim_scope_uncertain: bool
    citation_text: str
    url: str | None


@dataclass
class FetchResult:
    """What the live web server gave back. Raw observation, no judgement."""

    url: str
    status_code: int | None = None
    final_url: str | None = None
    content_type: str = ""
    error_kind: str | None = None
    title: str = ""
    first_heading: str = ""
    text: str = ""


@dataclass
class ArchiveResult:
    """What the Wayback Machine said. `lookup_failed` is never `not_found`."""

    outcome: str
    snapshot_url: str | None = None
    timestamp: str | None = None
    detail: str = ""
    # Set after the snapshot is fetched. A saved copy that is itself a robot check
    # is not evidence that the page exists.
    snapshot_is_bot_wall: bool = False


@dataclass
class UrlCheck:
    """One unique URL, checked once, with the text kept for the future model step."""

    url: str
    fetch: FetchResult
    archive: ArchiveResult
    label: str
    reason: str
    page_text: str


@dataclass
class FootnoteResult:
    """One row of results.json, in document order."""

    number: int
    marker: str
    line: int
    claim: str | None
    claim_scope_uncertain: bool
    citation_text: str
    url: str | None
    final_url: str | None
    status_code: int | None
    label: str
    reason: str
    archive_url: str | None
    archive_timestamp: str | None
    page_text_file: str | None


@dataclass
class Definition:
    """A footnote definition line, such as `[^2]: Smith 2020, https://...`."""

    marker: str
    line: int
    text: str
    url: str | None
    cited: bool = False


@dataclass
class Hit:
    """A place in the body that points at a source."""

    line: int
    column: int
    end_column: int
    key: str
    marker: str
    url: str | None
    citation_text: str


@dataclass
class Paragraph:
    """A block of body lines, joined, so a claim can span line breaks."""

    text: str
    line_starts: dict[int, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# HTML reading (pure)
# ---------------------------------------------------------------------------

SKIPPED_TAGS = ("script", "style", "noscript", "template")
BLOCK_TAGS = ("p", "div", "br", "li", "tr", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6")


class _HtmlReader(HTMLParser):
    """Shared plumbing: ignore the content of script and style tags."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIPPED_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIPPED_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1


class _MarkdownFromHtml(_HtmlReader):
    """Turn HTML into pseudo-markdown so one extractor handles both formats."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        super().handle_starttag(tag, attrs)
        if tag == "a":
            self._href = dict(attrs).get("href") or ""
            self.parts.append("[")
            return
        if tag in BLOCK_TAGS:
            self.parts.append("\n\n" if tag != "br" else "\n")

    def handle_endtag(self, tag: str) -> None:
        super().handle_endtag(tag)
        if tag == "a" and self._href is not None:
            self.parts.append(f"]({self._href})")
            self._href = None
            return
        if tag in BLOCK_TAGS:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self.parts.append(data.replace("\n", " "))


class _TextFromHtml(_HtmlReader):
    """Pull the title, the first h1 and the visible text out of a fetched page."""

    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.first_heading = ""
        self.parts: list[str] = []
        self._in_title = False
        self._in_h1 = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        super().handle_starttag(tag, attrs)
        self._in_title = self._in_title or tag == "title"
        self._in_h1 = self._in_h1 or tag == "h1"
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        super().handle_endtag(tag)
        if tag == "title":
            self._in_title = False
        if tag == "h1":
            self._in_h1 = False
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
        if self._in_h1 and not self.first_heading.strip():
            self.first_heading += data
        self.parts.append(data)


def html_to_markdown(html: str) -> str:
    """Convert an HTML document to pseudo-markdown text."""
    parser = _MarkdownFromHtml()
    parser.feed(html)
    parser.close()
    text = "".join(parser.parts)
    return re.sub(r"\n{3,}", "\n\n", text)


def html_to_text(html: str) -> tuple[str, str, str]:
    """Return the title, the first h1 and the readable text of an HTML page."""
    parser = _TextFromHtml()
    parser.feed(html)
    parser.close()
    body = re.sub(r"[ \t]+", " ", "".join(parser.parts))
    return parser.title.strip(), parser.first_heading.strip(), re.sub(r"\n{3,}", "\n\n", body).strip()


# ---------------------------------------------------------------------------
# Extraction (pure)
# ---------------------------------------------------------------------------


def clean_url(raw: str) -> str:
    """Drop the punctuation a writer left touching the end of a link."""
    url = raw.strip().rstrip(TRAILING_PUNCTUATION)
    # Only drop a closing bracket when the link has no opening one of its own,
    # so that links such as ...(disambiguation) survive.
    while url.endswith(")") and "(" not in url:
        url = url[:-1].rstrip(TRAILING_PUNCTUATION)
    return url


def is_checkable_url(url: str) -> bool:
    """Mail links, page anchors and relative links are not pages to fetch."""
    return url.startswith("http://") or url.startswith("https://")


def first_url_in(text: str) -> str | None:
    """Return the first web link inside a citation, if it has one."""
    match = URL_IN_TEXT_RE.search(text)
    if not match:
        return None
    url = clean_url(match.group(0))
    return url if is_checkable_url(url) else None


def strip_markers(text: str) -> str:
    """Remove footnote markers and link syntax so a claim reads as plain prose."""
    text = INLINE_LINK_RE.sub(r"\1", text)
    text = FOOTNOTE_MARKER_RE.sub("", text)
    text = NUMBER_MARKER_RE.sub("", text)
    return SPACE_BEFORE_PUNCTUATION_RE.sub(r"\1", " ".join(text.split()))


def sentence_spans(paragraph: str) -> list[tuple[int, int]]:
    """Split a paragraph into sentence spans, keeping offsets into the original."""
    spans: list[tuple[int, int]] = []
    start = 0
    for match in SENTENCE_BREAK_RE.finditer(paragraph):
        spans.append((start, match.start()))
        start = match.end()
    if start < len(paragraph):
        spans.append((start, len(paragraph)))
    return spans or [(0, len(paragraph))]


def claim_at(paragraph: str, start: int, end: int) -> tuple[str, bool]:
    """Return the sentence that carries the claim, and whether its scope is unclear."""
    spans = sentence_spans(paragraph)
    # A marker can sit in the gap between two sentences, where it belongs to the
    # sentence in front of it, so take the last sentence that starts at or before it.
    index = 0
    for position, (span_start, _span_end) in enumerate(spans):
        if span_start > start:
            break
        index = position
    claim = strip_markers(paragraph[spans[index][0] : spans[index][1]])
    # A marker parked after the full stop reads as its own empty sentence,
    # so the claim it supports is the sentence in front of it.
    while not claim and index > 0:
        index -= 1
        claim = strip_markers(paragraph[spans[index][0] : spans[index][1]])
    at_paragraph_end = not strip_markers(paragraph[end:])
    return claim, at_paragraph_end and len(spans) > 1


def parse_definitions(lines: list[str]) -> tuple[dict[str, Definition], list[bool]]:
    """Find every definition line and mark it so the body scan skips it."""
    definitions: dict[str, Definition] = {}
    is_definition = [False] * len(lines)
    for index, line in enumerate(lines):
        footnote = FOOTNOTE_DEF_RE.match(line)
        numbered = None if footnote else NUMBER_DEF_RE.match(line)
        match = footnote or numbered
        if not match:
            continue
        key = ("^" if footnote else "") + match.group(1)
        marker = f"[^{match.group(1)}]" if footnote else f"[{match.group(1)}]"
        body = match.group(2).strip()
        definitions[key] = Definition(marker, index + 1, body, first_url_in(body), False)
        is_definition[index] = True
    return definitions, is_definition


def build_paragraphs(lines: list[str], is_definition: list[bool]) -> dict[int, Paragraph]:
    """Group body lines into paragraphs and remember where each line starts."""
    by_line: dict[int, Paragraph] = {}
    current: Paragraph | None = None
    for index, line in enumerate(lines):
        if is_definition[index] or not line.strip():
            current = None
            continue
        if current is None:
            current = Paragraph(text="")
        # Keep the line as written so a hit column matches its paragraph offset.
        current.line_starts[index] = len(current.text)
        current.text += line.rstrip() + " "
        by_line[index] = current
    return by_line


def scan_line(line: str, index: int, definitions: dict[str, Definition]) -> list[Hit]:
    """Find every pointer to a source on one body line, in reading order."""
    hits: list[Hit] = []
    taken: list[tuple[int, int]] = []

    for match in INLINE_LINK_RE.finditer(line):
        taken.append(match.span())
        url = clean_url(match.group(2))
        if not is_checkable_url(url):
            continue
        hits.append(
            Hit(index, match.start(), match.end(), "", "inline", url, match.group(1).strip())
        )

    for match in FOOTNOTE_MARKER_RE.finditer(line):
        if _inside(match.span(), taken):
            continue
        taken.append(match.span())
        key = "^" + match.group(1)
        definition = definitions.get(key)
        hits.append(
            Hit(index, match.start(), match.end(), key, match.group(0),
                definition.url if definition else None,
                definition.text if definition else "")
        )

    for match in NUMBER_MARKER_RE.finditer(line):
        # A bare number in brackets is only a citation when a definition backs it.
        definition = definitions.get(match.group(1))
        if _inside(match.span(), taken) or definition is None:
            continue
        taken.append(match.span())
        hits.append(
            Hit(index, match.start(), match.end(), match.group(1), match.group(0),
                definition.url, definition.text)
        )

    for match in BARE_URL_RE.finditer(line):
        if _inside(match.span(), taken):
            continue
        taken.append(match.span())
        url = clean_url(match.group(0))
        hits.append(Hit(index, match.start(), match.end(), "", "inline", url, url))

    hits.sort(key=lambda hit: hit.column)
    return hits


def _inside(span: tuple[int, int], taken: list[tuple[int, int]]) -> bool:
    """True when a match sits within a span that an earlier pass already claimed."""
    return any(start <= span[0] < end for start, end in taken)


def extract_footnotes(document: str) -> list[Footnote]:
    """Pull every claim and its link out of a markdown or plain text document."""
    lines = document.splitlines()
    definitions, is_definition = parse_definitions(lines)
    paragraphs = build_paragraphs(lines, is_definition)

    footnotes: list[Footnote] = []
    for index, line in enumerate(lines):
        if is_definition[index] or not line.strip():
            continue
        for hit in scan_line(line, index, definitions):
            if hit.key in definitions:
                definitions[hit.key].cited = True
            paragraph = paragraphs[index]
            line_start = paragraph.line_starts[index]
            claim, uncertain = claim_at(
                paragraph.text, line_start + hit.column, line_start + hit.end_column
            )
            footnotes.append(
                Footnote(0, hit.marker, index + 1, claim, uncertain, hit.citation_text, hit.url)
            )

    for definition in definitions.values():
        if definition.cited:
            continue
        footnotes.append(
            Footnote(0, definition.marker, definition.line, None, False,
                     definition.text, definition.url)
        )

    footnotes.sort(key=lambda note: note.line)
    for position, footnote in enumerate(footnotes, start=1):
        footnote.number = position
    return footnotes


# ---------------------------------------------------------------------------
# Classification (pure)
# ---------------------------------------------------------------------------


def is_soft_404(title: str, first_heading: str) -> bool:
    """True when a page returns 200 but tells the reader it does not exist."""
    haystack = f"{title} {first_heading}".lower()
    return any(pattern in haystack for pattern in SOFT_404_PATTERNS)


def is_bot_wall(title: str, first_heading: str) -> bool:
    """True when the site showed a robot check instead of the page that was asked for."""
    haystack = f"{title} {first_heading}".lower()
    return any(pattern in haystack for pattern in BOT_WALL_PATTERNS)


def is_home_page_redirect(original: str, final: str | None) -> bool:
    """True when a deep link quietly landed on the site home page."""
    if not final:
        return False
    start, end = urllib.parse.urlparse(original), urllib.parse.urlparse(final)
    if start.hostname is None or end.hostname is None:
        return False
    if start.hostname.removeprefix("www.") != end.hostname.removeprefix("www."):
        return False
    return len(start.path) > 1 and end.path in ("", "/")


def _is_good_page(fetch: FetchResult) -> bool:
    """True when the page loaded and is really the page that was asked for."""
    if fetch.error_kind or fetch.status_code is None or not 200 <= fetch.status_code < 300:
        return False
    title, heading = fetch.title, fetch.first_heading
    if is_soft_404(title, heading) or is_bot_wall(title, heading):
        return False
    return not is_home_page_redirect(fetch.url, fetch.final_url)


def _is_page_missing(fetch: FetchResult) -> bool:
    """True when the evidence says the page is gone, not merely unreachable."""
    # A robot check is checked first because it proves nothing either way, even when
    # the wording of the block happens to mention a missing page.
    if is_bot_wall(fetch.title, fetch.first_heading):
        return False
    if fetch.status_code in MISSING_STATUS_CODES or fetch.error_kind == "dns":
        return True
    if fetch.error_kind or fetch.status_code is None:
        return False
    return is_soft_404(fetch.title, fetch.first_heading) or is_home_page_redirect(
        fetch.url, fetch.final_url
    )


def _live_phrase(fetch: FetchResult) -> str:
    """One plain clause describing what the live request did."""
    if fetch.error_kind == "dns":
        return "the domain name did not resolve"
    if fetch.error_kind == "timeout":
        return "the request timed out"
    if fetch.error_kind == "ssl":
        return "the security certificate could not be checked"
    if fetch.error_kind == "connection":
        return "the connection failed"
    if fetch.status_code is None:
        return "the request did not finish"
    if is_bot_wall(fetch.title, fetch.first_heading):
        return "the site showed a robot check instead of the page"
    if is_soft_404(fetch.title, fetch.first_heading):
        return f"the page returned {fetch.status_code} but the page itself says it is not found"
    if is_home_page_redirect(fetch.url, fetch.final_url):
        return "the link redirected to the site home page"
    if fetch.status_code in (401, 403):
        return f"the site returned {fetch.status_code} to scripts"
    return f"the page returned {fetch.status_code}"


def _archive_phrase(archive: ArchiveResult) -> str:
    """One plain clause describing what the archive said."""
    if archive.outcome == ARCHIVE_FOUND:
        if archive.snapshot_is_bot_wall:
            return "the archived copy is also a robot check page"
        when = f" from {format_timestamp(archive.timestamp)}" if archive.timestamp else ""
        return f"the archive has a saved copy{when}"
    if archive.outcome == ARCHIVE_NOT_FOUND:
        return "the archive has no copy"
    if archive.outcome == ARCHIVE_SKIPPED:
        return "archive checking was turned off"
    return f"the archive lookup failed{(' ' + archive.detail) if archive.detail else ''}"


def live_page_text(fetch: FetchResult) -> str:
    """The text worth keeping from a live fetch, which is none from a robot check."""
    # The future reading step must never judge a claim against a robot check page.
    if is_bot_wall(fetch.title, fetch.first_heading):
        return ""
    return fetch.text


def classify(fetch: FetchResult | None, archive: ArchiveResult) -> tuple[str, str]:
    """Turn one live result and one archive result into a label and a reason."""
    if fetch is None:
        return LABEL_NO_LINK, "This footnote gives no link, so there was nothing to fetch."
    if _is_good_page(fetch):
        return LABEL_LIVE, f"The page loaded with status {fetch.status_code}."

    missing = _is_page_missing(fetch)
    sentence = f"{_live_phrase(fetch)} and {_archive_phrase(archive)}".capitalize() + "."
    if archive.outcome == ARCHIVE_FOUND and not archive.snapshot_is_bot_wall:
        return (LABEL_DEAD_ARCHIVED if missing else LABEL_BLOCKED_ARCHIVED), sentence
    if archive.outcome == ARCHIVE_NOT_FOUND and missing:
        return LABEL_NEVER_ARCHIVED, sentence
    return LABEL_UNKNOWN, sentence


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------


def build_ssl_context() -> ssl.SSLContext:
    """Check certificates properly, borrowing the system bundle when Python has none."""
    context = ssl.create_default_context()
    if context.cert_store_stats()["x509_ca"] > 0:
        return context
    for candidate in CERT_BUNDLE_CANDIDATES:
        if Path(candidate).exists():
            context.load_verify_locations(cafile=candidate)
            return context
    # Verification is never turned off here. A tool that trusts any certificate
    # would report broken and hijacked links as healthy.
    return context


SSL_CONTEXT = build_ssl_context()


def _error_kind(error: Exception) -> str:
    """Name the kind of network failure in words a reader can act on."""
    reason = getattr(error, "reason", error)
    if isinstance(reason, socket.timeout) or isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(reason, ssl.SSLError) or isinstance(reason, ssl.SSLCertVerificationError):
        return "ssl"
    if isinstance(reason, socket.gaierror):
        return "dns"
    return "connection"


def _request(url: str, user_agent: str, timeout: float) -> tuple[int, str, str, bytes]:
    """Send one GET request and return status, final URL, content type and body."""
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
        body = response.read(MAX_DOWNLOAD_BYTES)
        content_type = response.headers.get("Content-Type", "")
        return response.status, response.geturl(), content_type, body


def _decode(body: bytes, content_type: str) -> str:
    """Decode a response body, guessing the character set from the header."""
    charset = "utf-8"
    for part in content_type.split(";"):
        if "charset=" in part:
            charset = part.split("charset=", 1)[1].strip().strip('"') or "utf-8"
    return body.decode(charset, errors="replace")


def fetch_page(url: str, timeout: float) -> FetchResult:
    """Ask for one page as a browser would and record what came back."""
    try:
        status, final_url, content_type, body = _request(url, BROWSER_USER_AGENT, timeout)
    except urllib.error.HTTPError as error:
        return FetchResult(url, error.code, error.url, error.headers.get("Content-Type", ""), "http")
    except (urllib.error.URLError, socket.timeout, TimeoutError, ssl.SSLError, OSError) as error:
        return FetchResult(url, None, None, "", _error_kind(error))

    if not any(hint in content_type.lower() for hint in TEXT_CONTENT_HINTS):
        note = f"[no text extracted: the server sent {content_type or 'an unknown file type'}]"
        return FetchResult(url, status, final_url, content_type, None, "", "", note)

    text = _decode(body, content_type)
    if "html" in content_type.lower():
        title, heading, plain = html_to_text(text)
        return FetchResult(url, status, final_url, content_type, None, title, heading, plain)
    return FetchResult(url, status, final_url, content_type, None, "", "", text.strip())


_last_archive_call = 0.0
_availability_is_refusing = False


def _archive_get(url: str, timeout: float) -> tuple[int, str]:
    """Call the archive once, gently, and return the status and the body."""
    global _last_archive_call
    wait = ARCHIVE_PAUSE_SECONDS - (time.monotonic() - _last_archive_call)
    if wait > 0:
        time.sleep(wait)
    try:
        status, _, content_type, body = _request(url, ARCHIVE_USER_AGENT, timeout)
        return status, _decode(body, content_type)
    except urllib.error.HTTPError as error:
        return error.code, ""
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError):
        return 0, ""
    finally:
        _last_archive_call = time.monotonic()


def _archive_get_with_retry(url: str, timeout: float) -> tuple[int, str]:
    """Retry the archive on the answers that mean 'busy', never on a real answer."""
    status, body = 0, ""
    for attempt in range(ARCHIVE_MAX_TRIES):
        status, body = _archive_get(url, timeout)
        if status not in ARCHIVE_RETRY_STATUS and status != 0:
            return status, body
        if attempt + 1 < ARCHIVE_MAX_TRIES:
            time.sleep(ARCHIVE_BACKOFF_SECONDS[attempt])
    return status, body


def _parse_availability(body: str) -> ArchiveResult | None:
    """Read the availability endpoint answer, or None when it made no sense."""
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return None
    closest = payload.get("archived_snapshots", {}).get("closest")
    if not closest or not closest.get("url"):
        return ArchiveResult(ARCHIVE_NOT_FOUND)
    return ArchiveResult(ARCHIVE_FOUND, closest["url"], closest.get("timestamp"))


def _parse_cdx(body: str) -> ArchiveResult | None:
    """Read the CDX answer, which is a header row followed by snapshot rows."""
    try:
        rows = json.loads(body)
    except (ValueError, TypeError):
        return None
    if not isinstance(rows, list):
        return None
    if len(rows) < 2:
        return ArchiveResult(ARCHIVE_NOT_FOUND)
    timestamp, original = rows[-1][0], rows[-1][1]
    snapshot = ARCHIVE_SNAPSHOT_TEMPLATE.format(timestamp=timestamp, original=original)
    return ArchiveResult(ARCHIVE_FOUND, snapshot, timestamp)


def archive_lookup(url: str, timeout: float) -> ArchiveResult:
    """Ask the Wayback Machine whether it kept a copy of a link."""
    global _availability_is_refusing
    quoted = urllib.parse.quote(url, safe="")

    # The availability endpoint answers anonymous callers with 429 on some networks.
    # Once it has refused in this run, go straight to CDX instead of knocking again.
    if not _availability_is_refusing:
        status, body = _archive_get_with_retry(ARCHIVE_AVAILABILITY_ENDPOINT + quoted, timeout)
        if status == 200:
            result = _parse_availability(body)
            if result is not None:
                return result
        _availability_is_refusing = True

    status, body = _archive_get_with_retry(ARCHIVE_CDX_ENDPOINT.format(url=quoted), timeout)
    if status == 200:
        result = _parse_cdx(body)
        if result is not None:
            return result
    return ArchiveResult(ARCHIVE_LOOKUP_FAILED, detail=f"after {ARCHIVE_MAX_TRIES} tries")


def fetch_snapshot(archive: ArchiveResult, timeout: float) -> FetchResult | None:
    """Fetch the archived page without the archive toolbar, for the later model step."""
    if not archive.timestamp or not archive.snapshot_url:
        return None
    original = ARCHIVE_SNAPSHOT_PREFIX_RE.sub("", archive.snapshot_url)
    url = ARCHIVE_RAW_SNAPSHOT_TEMPLATE.format(timestamp=archive.timestamp, original=original)
    return fetch_page(url, timeout)


# ---------------------------------------------------------------------------
# Running the check
# ---------------------------------------------------------------------------


def check_urls(urls: list[str], timeout: float, use_archive: bool) -> dict[str, UrlCheck]:
    """Check every unique URL once: live first in parallel, archive after, serially."""
    with ThreadPoolExecutor(max_workers=FETCH_THREADS) as pool:
        fetches = dict(zip(urls, pool.map(lambda url: _safe_fetch(url, timeout), urls)))

    checks: dict[str, UrlCheck] = {}
    for url in urls:
        fetch = fetches[url]
        archive = ArchiveResult(ARCHIVE_SKIPPED)
        page_text = live_page_text(fetch)
        if not _is_good_page(fetch) and use_archive:
            archive = _safe_archive(url, timeout)
            if archive.outcome == ARCHIVE_FOUND:
                page_text = _archived_text(archive, timeout)
        label, reason = classify(fetch, archive)
        if not page_text:
            page_text = f"[no text extracted: {_live_phrase(fetch)}]"
        checks[url] = UrlCheck(url, fetch, archive, label, reason, page_text)
    return checks


def _archived_text(archive: ArchiveResult, timeout: float) -> str:
    """Read the archived copy, and record when that copy is a robot check as well."""
    snapshot = fetch_snapshot(archive, timeout)
    if snapshot is None or not snapshot.text:
        # The copy exists but could not be read, so the label it earned still stands.
        return "[no text extracted: the archived copy could not be read]"
    if is_bot_wall(snapshot.title, snapshot.first_heading):
        archive.snapshot_is_bot_wall = True
        return "[no text extracted: the archived copy is also a robot check page]"
    return snapshot.text


def _safe_fetch(url: str, timeout: float) -> FetchResult:
    """Never let one broken URL end the run, and never hide why it broke."""
    try:
        return fetch_page(url, timeout)
    except Exception as error:  # noqa: BLE001 - the reason is reported, not swallowed
        return FetchResult(url, None, None, "", f"connection ({type(error).__name__}: {error})")


def _safe_archive(url: str, timeout: float) -> ArchiveResult:
    """Same rule for the archive: report the failure, keep going."""
    try:
        return archive_lookup(url, timeout)
    except Exception as error:  # noqa: BLE001 - the reason is reported, not swallowed
        return ArchiveResult(ARCHIVE_LOOKUP_FAILED, detail=f"({type(error).__name__}: {error})")


def build_results(
    footnotes: list[Footnote], checks: dict[str, UrlCheck], pages_written: dict[int, str]
) -> list[FootnoteResult]:
    """Join each footnote to the result for its URL. Every footnote appears once."""
    rows: list[FootnoteResult] = []
    for footnote in footnotes:
        check = checks.get(footnote.url) if footnote.url else None
        label, reason = (
            (check.label, check.reason) if check else classify(None, ArchiveResult(ARCHIVE_SKIPPED))
        )
        rows.append(
            FootnoteResult(
                number=footnote.number,
                marker=footnote.marker,
                line=footnote.line,
                claim=footnote.claim,
                claim_scope_uncertain=footnote.claim_scope_uncertain,
                citation_text=footnote.citation_text,
                url=footnote.url,
                final_url=check.fetch.final_url if check else None,
                status_code=check.fetch.status_code if check else None,
                label=label,
                reason=reason,
                archive_url=check.archive.snapshot_url if check else None,
                archive_timestamp=check.archive.timestamp if check else None,
                page_text_file=pages_written.get(footnote.number),
            )
        )
    return rows


def format_timestamp(timestamp: str | None) -> str:
    """Turn a Wayback timestamp such as 20190103120000 into 2019-01-03."""
    if not timestamp or len(timestamp) < 8 or not timestamp[:8].isdigit():
        return timestamp or ""
    return f"{timestamp[0:4]}-{timestamp[4:6]}-{timestamp[6:8]}"


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def build_report(input_name: str, rows: list[FootnoteResult]) -> str:
    """Write the plain English report a person reads before trusting a document."""
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.label] = counts.get(row.label, 0) + 1
    good = counts.get(LABEL_LIVE, 0)
    lines = [f"# Footnote check: {input_name}", ""]
    sentences = [
        f"This document has {len(rows)} footnote{'' if len(rows) == 1 else 's'}.",
        f"{good} of them {'points' if good == 1 else 'point'} at a page that loaded.",
        f"{len(rows) - good} {'needs' if len(rows) - good == 1 else 'need'} "
        "a person to look at them.",
    ]
    for label, count in sorted(counts.items()):
        if label != LABEL_LIVE:
            sentences.append(f"{count} {'is' if count == 1 else 'are'} marked \"{label}\".")
    lines.append(" ".join(sentences))
    lines += ["", "## Check these by hand", ""]
    flagged = [row for row in rows if row.label != LABEL_LIVE]
    if not flagged:
        lines.append("Nothing. Every link loaded.")
    for position, row in enumerate(flagged, start=1):
        lines.append(f"{position}. Footnote {row.number}, marker {row.marker}, line {row.line}.")
        lines.append(f"   Claim: {row.claim or 'this footnote is never cited in the text'}")
        lines.append(f"   Link: {row.url or 'none'}")
        lines.append(f"   Label: {row.label}")
        lines.append(f"   Why: {row.reason}")
        if row.archive_url:
            lines.append(f"   Archived copy: {row.archive_url}")
        lines.append("")
    lines += ["## Links that loaded", ""]
    live_rows = [row for row in rows if row.label == LABEL_LIVE]
    if not live_rows:
        lines.append("None.")
    for row in live_rows:
        lines.append(f"- Footnote {row.number}, line {row.line}: {row.url}")
    lines += ["", "## What this tool did not check", ""]
    lines.append(
        "A link that loaded only proves that the site answered at that address. "
        "Some sites answer every address, even invented ones, so a loaded link is weak evidence. "
        "Nobody has checked yet whether each page says what the footnote claims it says. "
        "That reading step is not built. "
        "Footnotes marked with an uncertain claim scope may cover more than the one sentence "
        "shown here, so read the whole paragraph before you judge them."
    )
    return "\n".join(lines) + "\n"


def write_outputs(out_dir: Path, payload: dict, report: str) -> None:
    """Save the machine readable results and the human readable report."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(report, encoding="utf-8")


def write_pages(out_dir: Path, footnotes: list[Footnote], checks: dict[str, UrlCheck]) -> dict[int, str]:
    """Save the page text for each footnote so a later model step can read it."""
    pages_dir = out_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    written: dict[int, str] = {}
    for footnote in footnotes:
        check = checks.get(footnote.url) if footnote.url else None
        if check is None:
            continue
        name = f"pages/{footnote.number}.txt"
        (out_dir / name).write_text(check.page_text, encoding="utf-8")
        written[footnote.number] = name
    return written


def read_input(path: Path) -> str:
    """Read the document, and stop with clear advice when that is not possible."""
    if not path.exists():
        _stop(f"There is no file at {path}.", "Check the path and run the command again.")
    if path.is_dir():
        _stop(f"{path} is a folder, not a file.", "Point the command at a .md, .txt or .html file.")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        _stop(f"The file {path} could not be read ({error}).", "Check the file permissions.")
    if not text.strip():
        _stop(f"The file {path} is empty.", "Save the document text into the file first.")
    return text


def _stop(problem: str, advice: str) -> None:
    """Fail loud on bad input: say what broke, why, and what to do."""
    print(f"curl-my-footnotes stopped. {problem} {advice}", file=sys.stderr)
    raise SystemExit(EXIT_INPUT_ERROR)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Read the command line."""
    parser = argparse.ArgumentParser(description="Check that the footnotes of a document still load.")
    parser.add_argument("input", help="A .md, .txt or .html file to check.")
    parser.add_argument("--out-dir", default=None, help="Where to write the results.")
    parser.add_argument("--no-archive", action="store_true", help="Skip the Wayback Machine.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS,
                        help="Seconds to wait for each page.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the whole check and return 0 whenever the run itself completed."""
    args = parse_args(argv)
    if SSL_CONTEXT.cert_store_stats()["x509_ca"] == 0:
        print("Warning: this computer has no certificate bundle that Python can read, "
              "so every secure link will be reported as unchecked.", file=sys.stderr)
    input_path = Path(args.input).expanduser()
    document = read_input(input_path)
    if input_path.suffix.lower() in (".html", ".htm"):
        document = html_to_markdown(document)

    footnotes = extract_footnotes(document)
    urls = list(dict.fromkeys(note.url for note in footnotes if note.url))
    checks = check_urls(urls, args.timeout, not args.no_archive)

    out_dir = Path(args.out_dir) if args.out_dir else Path(f"./footnote-check-{input_path.stem}")
    out_dir.mkdir(parents=True, exist_ok=True)
    pages_written = write_pages(out_dir, footnotes, checks)
    rows = build_results(footnotes, checks, pages_written)

    counts: dict[str, int] = {}
    for row in rows:
        counts[row.label] = counts.get(row.label, 0) + 1
    payload = {
        "input": str(input_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool_version": TOOL_VERSION,
        "counts": counts,
        "footnotes": [asdict(row) for row in rows],
    }
    report = build_report(input_path.name, rows)
    write_outputs(out_dir, payload, report)
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
