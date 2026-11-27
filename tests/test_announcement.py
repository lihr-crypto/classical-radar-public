"""First-announcement-date detector (P0.3): strict about what counts as a publication date. No network."""
import json
import unittest

from classical_radar.announcement import SNIPPET_MAX, classify, signals, source_level


def page(head="", body=""):
    return f"<html><head>{head}</head><body>{body}</body></html>"


def kinds(html):
    return {(s["kind"], s["class"], s["date"]) for s in signals(html)}


class SignalTests(unittest.TestCase):
    def test_machine_readable_published_and_modified(self):
        ld = json.dumps({"@type": "Event", "datePublished": "2026-09-01T10:00:00+09:00", "dateModified": "2026-10-20", "dateCreated": "2026-08-30"})
        html = page(f'<script type="application/ld+json">{ld}</script>'
                    '<meta property="article:published_time" content="2026-09-01T01:00:00+00:00">'
                    '<meta property="article:modified_time" content="2026-10-20T01:00:00+00:00">')
        self.assertEqual(kinds(html), {("json_ld_published", "published", "2026-09-01"), ("json_ld_modified", "update_only", "2026-10-20"), ("json_ld_created", "ambiguous", "2026-08-30"),
                                       ("meta_published", "published", "2026-09-01"), ("meta_modified", "update_only", "2026-10-20")})

    def test_labelled_text_publication_vs_update(self):
        html = page(body="<p>公開日：2026年9月1日</p><p>最終更新日 2026.10.20</p><p>掲載日: 2026/9/3</p>")
        self.assertEqual({(k, c) for k, c, _ in kinds(html)}, {("labelled_published", "published"), ("labelled_updated", "update_only")})
        self.assertEqual({d for k, _, d in kinds(html) if k == "labelled_published"}, {"2026-09-01", "2026-09-03"})

    def test_an_update_date_is_never_a_first_announcement(self):
        sig = signals(page(body="<p>更新日：2026年10月20日</p>"))
        self.assertEqual(classify(sig, ["2027-02-07"]), "update_only")

    def test_a_bare_date_element_is_ambiguous_like_kanagawas_performance_date(self):
        # kanagawa-geikyo's `.published` span holds the PERFORMANCE date and has no label: it must never count as an announcement
        html = page(body='<span class="published">2026年11月11日(水)</span><time datetime="2026-11-11">11/11</time>')
        sig = signals(html)
        self.assertEqual({s["class"] for s in sig}, {"ambiguous"})
        self.assertEqual(classify(sig, ["2026-11-11"]), "ambiguous")

    def test_a_bare_date_in_a_date_class_element_is_ambiguous_like_nhks_news_date(self):
        # NHK響's news page prints the article date in <span class="date">2026年7月 1日</span> with no label
        sig = signals(page(body='<div class="attr"><span class="type">お知らせ</span><span class="date">2026年7月 1日</span></div>'))
        self.assertEqual([(s["kind"], s["class"], s["date"]) for s in sig], [("class_date", "ambiguous", "2026-07-01")])
        self.assertEqual(classify(sig, []), "ambiguous")
        self.assertEqual(signals(page(body='<span class="date">開演 2026年7月1日 19:00 サントリーホール</span>')), [])  # text with more than a date is not a bare date

    def test_published_counts_only_before_the_earliest_performance_date(self):
        sig = signals(page(body="<p>公開日：2026年9月1日</p>"))
        self.assertEqual(classify(sig, ["2026-12-01", "2027-01-01"]), "published")
        self.assertEqual(classify(sig, ["2026-09-01"]), "ambiguous")      # same day as the concert: probably not an announcement
        self.assertEqual(classify(sig, ["2026-08-01"]), "ambiguous")      # after the concert
        self.assertEqual(classify(sig, []), "ambiguous")                  # no performance date to compare with
        self.assertEqual(classify([], ["2027-01-01"]), "none")

    def test_nothing_on_the_page_is_none(self):
        self.assertEqual(signals(page(body="<p>コンサート情報</p>")), [])

    def test_snippets_are_short_and_dates_normalised(self):
        long = "公開日：2026年9月1日 " + "あ" * 500
        for s in signals(page(body=f"<p>{long}</p>")):
            self.assertLessEqual(len(s["snippet"]), SNIPPET_MAX)
        self.assertEqual(kinds(page(body="<p>Published: 2026-9-1</p>")), {("labelled_published", "published", "2026-09-01")})

    def test_garbage_json_ld_and_impossible_dates_are_ignored(self):
        html = page('<script type="application/ld+json">{not json</script><meta property="article:published_time" content="1999-01-01">'
                    '<meta property="article:modified_time" content="2026-13-40">')
        self.assertEqual(signals(html), [])


class SourceLevelTests(unittest.TestCase):
    def pages(self, *dates, perf="2027-03-01", kind="meta"):
        mk = (lambda d: page(f'<meta property="article:published_time" content="{d}">')) if kind == "meta" else (lambda d: page(body=f"<p>公開日：{d}</p>"))
        return [{"signals": signals(mk(d)), "performance_dates": [perf]} for d in dates]

    def test_a_machine_stamp_repeated_on_every_page_is_a_template_stamp(self):
        self.assertEqual(source_level(self.pages("2026-01-01", "2026-01-01", "2026-01-01")), ["ambiguous"] * 3)

    def test_a_single_page_cannot_show_that_the_stamp_varies(self):
        self.assertEqual(source_level(self.pages("2026-01-01")), ["ambiguous"])

    def test_machine_stamps_that_differ_across_pages_count(self):
        self.assertEqual(source_level(self.pages("2026-01-01", "2026-02-10")), ["published", "published"])

    def test_labelled_dates_keep_their_verdict_even_if_equal_on_two_pages(self):
        self.assertEqual(source_level(self.pages("2026-01-01", "2026-01-01", kind="label")), ["published", "published"])


if __name__ == "__main__":
    unittest.main()
