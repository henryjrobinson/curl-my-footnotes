"""Offline tests for check_footnotes. Nothing here touches the network."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check_footnotes as cf  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample.md"

EM_DASH = "—"
ARROW = "→"

SAMPLE_HTML = """<html><head><title>A page</title></head><body>
<script>var trap = "[not a link](http://bad.example/hidden)";</script>
<style>a { color: red; }</style>
<p>Claude says the sky is blue. See <a href="https://example.com/proof">the proof</a>.</p>
</body></html>"""


def live_fetch(url: str, status: int = 200, title: str = "A real page") -> cf.FetchResult:
    """Build a fetch result that looks like a page that loaded."""
    return cf.FetchResult(url=url, status_code=status, final_url=url, content_type="text/html",
                          title=title, text="body text")


class ExtractionTests(unittest.TestCase):
    """Step 0 turns a document into footnote records without any network."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.notes = cf.extract_footnotes(FIXTURE.read_text(encoding="utf-8"))

    def note(self, number: int) -> cf.Footnote:
        return self.notes[number - 1]

    def test_document_order_and_count(self) -> None:
        self.assertEqual(len(self.notes), 7)
        self.assertEqual([note.number for note in self.notes], list(range(1, 8)))
        self.assertEqual([note.line for note in self.notes], [3, 5, 7, 9, 11, 15, 19])

    def test_markdown_footnote(self) -> None:
        note = self.note(1)
        self.assertEqual(note.marker, "[^1]")
        self.assertEqual(note.claim, "The sky is blue.")
        self.assertEqual(note.url, "https://example.com/smith")
        self.assertEqual(note.citation_text, "Smith 2020, https://example.com/smith")
        self.assertFalse(note.claim_scope_uncertain)

    def test_numbered_reference(self) -> None:
        note = self.note(3)
        self.assertEqual(note.marker, "[1]")
        self.assertEqual(note.claim, "The study found a clear effect.")
        self.assertEqual(note.url, "https://example.com/ref")

    def test_inline_link(self) -> None:
        note = self.note(4)
        self.assertEqual(note.marker, "inline")
        self.assertEqual(note.claim, "See the project page for details.")
        self.assertEqual(note.url, "https://example.com/project")

    def test_bare_url_and_trailing_punctuation(self) -> None:
        note = self.note(5)
        self.assertEqual(note.marker, "inline")
        self.assertEqual(note.url, "https://example.com/raw")

    def test_definition_without_url(self) -> None:
        note = self.note(2)
        self.assertEqual(note.marker, "[^2]")
        self.assertIsNone(note.url)
        self.assertEqual(note.citation_text, "A book with no link, Jones 2019.")

    def test_definition_never_cited(self) -> None:
        note = self.note(7)
        self.assertEqual(note.marker, "[^9]")
        self.assertIsNone(note.claim)
        self.assertEqual(note.url, "https://example.com/orphan")

    def test_one_definition_cited_twice(self) -> None:
        cited = [note for note in self.notes if note.marker == "[^1]"]
        self.assertEqual(len(cited), 2)
        self.assertEqual([note.claim for note in cited],
                         ["The sky is blue.", "The moon is bright."])
        self.assertEqual({note.url for note in cited}, {"https://example.com/smith"})

    def test_marker_at_end_of_multi_sentence_paragraph(self) -> None:
        note = self.note(2)
        self.assertTrue(note.claim_scope_uncertain)
        self.assertEqual(note.claim, "They do this every year.")

    def test_single_sentence_paragraph_is_not_uncertain(self) -> None:
        self.assertFalse(self.note(6).claim_scope_uncertain)

    def test_mail_anchor_and_relative_links_are_skipped(self) -> None:
        urls = [note.url for note in self.notes]
        self.assertNotIn("mailto:a@b.com", urls)
        self.assertNotIn("#section", urls)
        self.assertNotIn("/local/page", urls)

    def test_url_cleaning_keeps_balanced_brackets(self) -> None:
        self.assertEqual(cf.clean_url("https://x.test/a_(b)"), "https://x.test/a_(b)")
        self.assertEqual(cf.clean_url("https://x.test/a);"), "https://x.test/a")


class HtmlInputTests(unittest.TestCase):
    """HTML input becomes pseudo-markdown, then goes through the same extractor."""

    def test_html_is_converted_then_extracted(self) -> None:
        markdown = cf.html_to_markdown(SAMPLE_HTML)
        self.assertIn("[the proof](https://example.com/proof)", markdown)
        notes = cf.extract_footnotes(markdown)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].url, "https://example.com/proof")
        self.assertEqual(notes[0].claim, "See the proof.")

    def test_script_and_style_content_is_dropped(self) -> None:
        markdown = cf.html_to_markdown(SAMPLE_HTML)
        self.assertNotIn("bad.example", markdown)
        self.assertNotIn("color: red", markdown)

    def test_page_text_extraction_reads_title_and_heading(self) -> None:
        title, heading, text = cf.html_to_text(
            "<html><head><title>Gone</title></head><body><h1>Page not found</h1>"
            "<p>Sorry.</p></body></html>"
        )
        self.assertEqual(title, "Gone")
        self.assertEqual(heading, "Page not found")
        self.assertIn("Sorry.", text)


class ClassifyTests(unittest.TestCase):
    """classify is pure, so every case is built from dataclasses, not mocks."""

    def test_live(self) -> None:
        label, reason = cf.classify(live_fetch("https://a.test/page"),
                                    cf.ArchiveResult(cf.ARCHIVE_SKIPPED))
        self.assertEqual(label, cf.LABEL_LIVE)
        self.assertIn("200", reason)

    def test_dead_with_archive(self) -> None:
        fetch = cf.FetchResult("https://a.test/gone", 404, "https://a.test/gone", error_kind="http")
        archive = cf.ArchiveResult(cf.ARCHIVE_FOUND, "https://web.archive.org/web/2019/x", "20190103")
        label, reason = cf.classify(fetch, archive)
        self.assertEqual(label, cf.LABEL_DEAD_ARCHIVED)
        self.assertIn("2019-01-03", reason)

    def test_never_archived_is_only_for_a_missing_page(self) -> None:
        fetch = cf.FetchResult("https://a.test/gone", 404, "https://a.test/gone", error_kind="http")
        label, _ = cf.classify(fetch, cf.ArchiveResult(cf.ARCHIVE_NOT_FOUND))
        self.assertEqual(label, cf.LABEL_NEVER_ARCHIVED)

    def test_dns_failure_counts_as_missing(self) -> None:
        fetch = cf.FetchResult("https://nope.test/report", error_kind="dns")
        label, reason = cf.classify(fetch, cf.ArchiveResult(cf.ARCHIVE_NOT_FOUND))
        self.assertEqual(label, cf.LABEL_NEVER_ARCHIVED)
        self.assertIn("domain name did not resolve", reason)

    def test_blocked_live_with_archive(self) -> None:
        fetch = cf.FetchResult("https://a.test/x", 403, "https://a.test/x", error_kind="http")
        archive = cf.ArchiveResult(cf.ARCHIVE_FOUND, "https://web.archive.org/web/2020/x", "20200201")
        label, _ = cf.classify(fetch, archive)
        self.assertEqual(label, cf.LABEL_BLOCKED_ARCHIVED)

    def test_blocked_live_without_archive_is_unknown(self) -> None:
        fetch = cf.FetchResult("https://a.test/x", 403, "https://a.test/x", error_kind="http")
        label, reason = cf.classify(fetch, cf.ArchiveResult(cf.ARCHIVE_NOT_FOUND))
        self.assertEqual(label, cf.LABEL_UNKNOWN)
        self.assertIn("403", reason)
        self.assertIn("no copy", reason)

    def test_lookup_failure_never_accuses_the_link(self) -> None:
        fetch = cf.FetchResult("https://a.test/gone", 404, "https://a.test/gone", error_kind="http")
        archive = cf.ArchiveResult(cf.ARCHIVE_LOOKUP_FAILED, detail="after 3 tries")
        label, reason = cf.classify(fetch, archive)
        self.assertEqual(label, cf.LABEL_UNKNOWN)
        self.assertNotEqual(label, cf.LABEL_NEVER_ARCHIVED)
        self.assertIn("archive lookup failed after 3 tries", reason)

    def test_no_archive_option(self) -> None:
        fetch = cf.FetchResult("https://a.test/gone", 404, "https://a.test/gone", error_kind="http")
        label, reason = cf.classify(fetch, cf.ArchiveResult(cf.ARCHIVE_SKIPPED))
        self.assertEqual(label, cf.LABEL_UNKNOWN)
        self.assertIn("turned off", reason)

    def test_no_link(self) -> None:
        label, reason = cf.classify(None, cf.ArchiveResult(cf.ARCHIVE_SKIPPED))
        self.assertEqual(label, cf.LABEL_NO_LINK)
        self.assertIn("no link", reason)

    def test_soft_404(self) -> None:
        fetch = live_fetch("https://a.test/deep", title="404 Not Found")
        label, reason = cf.classify(fetch, cf.ArchiveResult(cf.ARCHIVE_NOT_FOUND))
        self.assertEqual(label, cf.LABEL_NEVER_ARCHIVED)
        self.assertIn("says it is not found", reason)

    def test_soft_404_detection_is_case_insensitive(self) -> None:
        self.assertTrue(cf.is_soft_404("", "PAGE NOT FOUND"))
        self.assertTrue(cf.is_soft_404("No Longer Available", ""))
        self.assertFalse(cf.is_soft_404("A normal article", "A normal heading"))

    def test_home_page_redirect(self) -> None:
        fetch = cf.FetchResult("https://a.test/deep/page", 200, "https://www.a.test/",
                               content_type="text/html", title="A Test")
        label, reason = cf.classify(fetch, cf.ArchiveResult(cf.ARCHIVE_NOT_FOUND))
        self.assertEqual(label, cf.LABEL_NEVER_ARCHIVED)
        self.assertIn("home page", reason)

    def test_home_page_redirect_rules(self) -> None:
        self.assertTrue(cf.is_home_page_redirect("https://a.test/deep", "https://a.test/"))
        self.assertFalse(cf.is_home_page_redirect("https://a.test/", "https://a.test/"))
        self.assertFalse(cf.is_home_page_redirect("https://a.test/deep", "https://b.test/"))
        self.assertFalse(cf.is_home_page_redirect("https://a.test/deep", "https://a.test/other"))

    def test_pdf_content_still_counts_as_live(self) -> None:
        fetch = cf.FetchResult("https://a.test/paper.pdf", 200, "https://a.test/paper.pdf",
                               content_type="application/pdf", text="[no text extracted]")
        label, _ = cf.classify(fetch, cf.ArchiveResult(cf.ARCHIVE_SKIPPED))
        self.assertEqual(label, cf.LABEL_LIVE)


class BotWallTests(unittest.TestCase):
    """A robot check page means the tool never saw the real page, so it proves nothing."""

    def wall(self, title: str = "Client Challenge") -> cf.FetchResult:
        return cf.FetchResult(url="https://walled.test/article/1", status_code=200,
                              final_url="https://walled.test/article/1",
                              content_type="text/html", title=title,
                              text="A required part of this site could not load.")

    def test_bot_wall_with_archive_is_blocked_not_live(self) -> None:
        archive = cf.ArchiveResult(cf.ARCHIVE_FOUND, "https://web.archive.org/web/2020/x", "20200201")
        label, reason = cf.classify(self.wall(), archive)
        self.assertEqual(label, cf.LABEL_BLOCKED_ARCHIVED)
        self.assertIn("robot check", reason)

    def test_bot_wall_without_archive_is_unknown_not_invented(self) -> None:
        label, _ = cf.classify(self.wall(), cf.ArchiveResult(cf.ARCHIVE_NOT_FOUND))
        self.assertEqual(label, cf.LABEL_UNKNOWN)
        self.assertNotEqual(label, cf.LABEL_NEVER_ARCHIVED)
        self.assertNotEqual(label, cf.LABEL_LIVE)

    def test_bot_wall_with_archive_skipped_is_unknown(self) -> None:
        label, _ = cf.classify(self.wall(), cf.ArchiveResult(cf.ARCHIVE_SKIPPED))
        self.assertEqual(label, cf.LABEL_UNKNOWN)

    def test_an_ordinary_page_is_still_live(self) -> None:
        label, _ = cf.classify(live_fetch("https://a.test/page"),
                               cf.ArchiveResult(cf.ARCHIVE_SKIPPED))
        self.assertEqual(label, cf.LABEL_LIVE)

    def test_every_pattern_is_matched_whatever_the_case(self) -> None:
        for pattern in cf.BOT_WALL_PATTERNS:
            self.assertTrue(cf.is_bot_wall(pattern.upper(), ""), pattern)
            self.assertTrue(cf.is_bot_wall("", f"Site says: {pattern}"), pattern)
        self.assertFalse(cf.is_bot_wall("A normal article", "A normal heading"))

    def test_a_robot_check_is_never_called_missing(self) -> None:
        # A block that mentions a missing page must not read as proof the page is gone.
        fetch = self.wall(title="Access Denied: page not found")
        label, _ = cf.classify(fetch, cf.ArchiveResult(cf.ARCHIVE_NOT_FOUND))
        self.assertEqual(label, cf.LABEL_UNKNOWN)

    def test_archived_robot_check_is_not_evidence_when_live_is_unclear(self) -> None:
        archive = cf.ArchiveResult(cf.ARCHIVE_FOUND, "https://web.archive.org/web/2026/x",
                                   "20260622", snapshot_is_bot_wall=True)
        label, reason = cf.classify(self.wall(), archive)
        self.assertEqual(label, cf.LABEL_UNKNOWN)
        self.assertIn("the archived copy is also a robot check page", reason)

    def test_archived_robot_check_is_not_evidence_when_the_page_is_missing(self) -> None:
        fetch = cf.FetchResult("https://a.test/gone", 404, "https://a.test/gone", error_kind="http")
        archive = cf.ArchiveResult(cf.ARCHIVE_FOUND, "https://web.archive.org/web/2026/x",
                                   "20260622", snapshot_is_bot_wall=True)
        label, reason = cf.classify(fetch, archive)
        self.assertEqual(label, cf.LABEL_UNKNOWN)
        self.assertNotEqual(label, cf.LABEL_DEAD_ARCHIVED)
        self.assertIn("the archived copy is also a robot check page", reason)

    def test_a_normal_archived_copy_still_earns_the_archived_labels(self) -> None:
        good_archive = cf.ArchiveResult(cf.ARCHIVE_FOUND, "https://web.archive.org/web/2026/x",
                                        "20260622")
        self.assertFalse(good_archive.snapshot_is_bot_wall)
        blocked, _ = cf.classify(self.wall(), good_archive)
        self.assertEqual(blocked, cf.LABEL_BLOCKED_ARCHIVED)
        gone = cf.FetchResult("https://a.test/gone", 404, "https://a.test/gone", error_kind="http")
        dead, reason = cf.classify(gone, good_archive)
        self.assertEqual(dead, cf.LABEL_DEAD_ARCHIVED)
        self.assertIn("the archive has a saved copy", reason)

    def test_robot_check_text_is_never_kept_for_reading(self) -> None:
        self.assertEqual(cf.live_page_text(self.wall()), "")
        real = live_fetch("https://a.test/page")
        self.assertEqual(cf.live_page_text(real), real.text)


class ArchiveParsingTests(unittest.TestCase):
    """Reading the archive answer is pure, so it is tested without the network."""

    CDX_HIT = '[["timestamp","original"],["20210503140021","https://www.google.com/reader/about/"]]'

    def test_cdx_snapshot_url_is_the_form_a_person_clicks(self) -> None:
        result = cf._parse_cdx(self.CDX_HIT)
        self.assertEqual(result.outcome, cf.ARCHIVE_FOUND)
        self.assertEqual(result.timestamp, "20210503140021")
        self.assertNotIn("id_", result.snapshot_url)
        self.assertEqual(
            result.snapshot_url,
            "https://web.archive.org/web/20210503140021/https://www.google.com/reader/about/",
        )

    def test_cdx_header_row_alone_means_no_copy(self) -> None:
        self.assertEqual(cf._parse_cdx('[["timestamp","original"]]').outcome, cf.ARCHIVE_NOT_FOUND)

    def test_availability_answers(self) -> None:
        self.assertEqual(
            cf._parse_availability('{"archived_snapshots":{}}').outcome, cf.ARCHIVE_NOT_FOUND
        )
        found = ('{"archived_snapshots":{"closest":{"url":"http://web.archive.org/web/2021/x",'
                 '"timestamp":"20210503140021","available":true}}}')
        self.assertEqual(cf._parse_availability(found).outcome, cf.ARCHIVE_FOUND)

    def test_an_error_page_is_never_read_as_no_copy(self) -> None:
        for body in ("<html><body><h1>429 Too Many Requests</h1></body></html>", "", "not json"):
            self.assertIsNone(cf._parse_cdx(body), body)
            self.assertIsNone(cf._parse_availability(body), body)

    def test_timestamp_formatting(self) -> None:
        self.assertEqual(cf.format_timestamp("20210503140021"), "2021-05-03")
        self.assertEqual(cf.format_timestamp(None), "")


class ReportTests(unittest.TestCase):
    """Every footnote must survive into the results and the report, exactly once."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.notes = cf.extract_footnotes(FIXTURE.read_text(encoding="utf-8"))
        checks = {}
        for url in {note.url for note in cls.notes if note.url}:
            status = 404 if "orphan" in url else 200
            fetch = live_fetch(url, status=status)
            archive = cf.ArchiveResult(cf.ARCHIVE_NOT_FOUND if status == 404 else cf.ARCHIVE_SKIPPED)
            label, reason = cf.classify(fetch, archive)
            checks[url] = cf.UrlCheck(url, fetch, archive, label, reason, "page text")
        cls.rows = cf.build_results(cls.notes, checks, {})
        cls.report = cf.build_report("sample.md", cls.rows)

    def test_every_footnote_appears_once_in_results(self) -> None:
        self.assertEqual(len(self.rows), len(self.notes))
        numbers = [row.number for row in self.rows]
        self.assertEqual(numbers, sorted(set(numbers)))

    def test_every_footnote_appears_once_in_the_report(self) -> None:
        for row in self.rows:
            self.assertEqual(self.report.count(f"Footnote {row.number},"), 1,
                             f"footnote {row.number} is not listed exactly once")

    def test_summary_counts_read_as_english(self) -> None:
        live_rows = [row for row in self.rows if row.label == cf.LABEL_LIVE]
        flagged_rows = [row for row in self.rows if row.label != cf.LABEL_LIVE]

        one_live = cf.build_report("d", live_rows[:1])
        self.assertIn("This document has 1 footnote.", one_live)
        self.assertIn("1 of them points at a page that loaded.", one_live)
        self.assertIn("0 need a person to look at them.", one_live)

        one_flagged = cf.build_report("d", flagged_rows[:1])
        self.assertIn("1 needs a person to look at them.", one_flagged)

        self.assertIn("point at a page that loaded.", cf.build_report("d", self.rows))

    def test_report_has_no_em_dash_or_arrow(self) -> None:
        self.assertNotIn(EM_DASH, self.report)
        self.assertNotIn(ARROW, self.report)

    def test_report_states_what_was_not_checked(self) -> None:
        self.assertIn("What this tool did not check", self.report)
        self.assertIn("only proves that the site answered at that address", self.report)
        self.assertIn("Some sites answer every address, even invented ones", self.report)

    def test_report_never_calls_a_link_verified(self) -> None:
        for banned in ("verified", "supported", "confirmed"):
            self.assertNotIn(banned, self.report.lower())


class SecurityTests(unittest.TestCase):
    """A link checker that trusts any certificate would report bad links as healthy."""

    def test_certificate_checking_is_never_turned_off(self) -> None:
        context = cf.build_ssl_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, cf.ssl.CERT_REQUIRED)

    def test_a_certificate_bundle_is_found(self) -> None:
        self.assertGreater(cf.SSL_CONTEXT.cert_store_stats()["x509_ca"], 0)


class InputTests(unittest.TestCase):
    """Bad input must stop the run with exit code 2 and a clear message."""

    def test_missing_file_exits_with_code_two(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            cf.read_input(Path("/nonexistent/path/to/doc.md"))
        self.assertEqual(caught.exception.code, cf.EXIT_INPUT_ERROR)

    def test_empty_file_exits_with_code_two(self) -> None:
        empty = Path(__file__).resolve().parent / "fixtures" / "_empty_for_test.md"
        empty.write_text("   \n", encoding="utf-8")
        try:
            with self.assertRaises(SystemExit) as caught:
                cf.read_input(empty)
            self.assertEqual(caught.exception.code, cf.EXIT_INPUT_ERROR)
        finally:
            empty.unlink()


if __name__ == "__main__":
    unittest.main()
