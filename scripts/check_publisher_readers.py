"""Synthetic offline contracts for publisher recovery and rules 22 narration."""

import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import Mock, patch
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_daily_news_brief import IsolatedChecks, NOW
from scripts.check_disclosure_intelligence import source, EditionChecks as DisclosureFixture
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from src.intelligence import news_original_sources as originals, news_live_sources as feeds
from src.intelligence import northrop_newsroom as noc, news_editor as editor, news_editor_store as store
from src.intelligence.special_alert_company_sources import publication_time
from src.reports.daily_news_brief import build_daily_news_brief
from src.reports import daily_voiceover as voice
from src.utils.speech_text import normalize


READ_NOW = datetime(2026, 11, 4, 11, 33, tzinfo=timezone.utc)
AMD = next(row for row in feeds.NEWS_SOURCES if row.get("company_symbol") == "AMD")
NORTHROP = next(row for row in feeds.NEWS_SOURCES if row.get("newsroom_home_fallback"))
AMD_URL = "https://ir.amd.com/news-events/press-releases/detail/9999/synthetic-quarterly-results"
AMD_TITLE = "AMD Reports Third Quarter 2026 Financial Results"
AMD_PUBLISHED = "Tue, 03 Nov 26 16:15:00 -0500"
NOC_URL = "https://news.northropgrumman.com/navigation-systems/northrop-grumman-announces-example-navigation-system"
NOC_TITLE = "Northrop Grumman Announces Example Navigation System"
NOC_PUBLISHED = "2026-11-04T10:00:00Z"


def payload(url, body="", **extra):
    return {"url":url, "final_url":url, "status":"ok", "body":body, "fetched_at_epoch":READ_NOW.timestamp(), **extra}


def amd_page(day="03", month="November", *, original_clock="", title=AMD_TITLE):
    meta = f'<meta property="article:published_time" content="{original_clock}">' if original_clock else ""
    return (f'<meta property="og:title" content="{title}">{meta}<article><h1>{title}</h1>'
        f'<time class="date" datetime="2026-11-03T16:15:00">{month} {day}, 2026 4:15 pm EST</time>'
        '<p>AMD announced results for the third quarter of 2026. Third quarter revenue was $8.8 billion.</p></article>')


def amd_rss():
    return f'<rss><channel><item><title>{AMD_TITLE}</title><link>{AMD_URL}</link><pubDate>{AMD_PUBLISHED}</pubDate></item></channel></rss>'


def noc_home(*, url=NOC_URL, title=NOC_TITLE):
    return (f'<a href="/Media-Contacts">Media Contacts</a><a href="{url}" class="NewsroomHeroCarousel_headline__abc">{title}</a>'
        f'<a href="{url}" aria-label="Read More about {title}">Read More</a>')


def noc_page(*, title=NOC_TITLE, canonical=NOC_URL, clock=NOC_PUBLISHED, extra=""):
    return (f'<meta property="og:title" content="{title}"><meta property="og:url" content="{canonical}">'
        f'<meta property="og:publishDate" content="{clock}">{extra}<h1>{title}</h1>'
        '<div class="NewsroomArticleBody_BodyCopy__abc"><p>Northrop Grumman introduced an example navigation system for a synthetic test program.</p></div>'
        '<div class="NewsroomArticleBody_SideColumn__abc">Unrelated media contacts and site navigation.</div>')


class AMDChecks(unittest.TestCase):
    def read(self, body):
        return originals.article_excerpt(body,AMD_TITLE,AMD_PUBLISHED,publisher=AMD["name"],url=AMD_URL)

    def test_zero_padded_and_unpadded_original_days_are_equivalent(self):
        for day in ("03", "3"):
            self.assertIn("$8.8 billion", self.read(amd_page(day)))

    def test_full_and_abbreviated_months_retain_the_original_feed_clock(self):
        for month in ("November", "Nov", "Nov."):
            self.assertTrue(self.read(amd_page(month=month)))

    def test_a_conflicting_header_date_is_not_replaced_by_a_matching_body_date(self):
        body = amd_page("04").replace("AMD announced", "Nov. 03, 2026. AMD announced")
        with self.assertRaises(ValueError):self.read(body)

    def test_other_month_year_and_extra_zero_dates_remain_held(self):
        for body in (amd_page(month="October"), amd_page().replace("2026", "2025"), amd_page("003")):
            with self.assertRaises(ValueError):self.read(body)

    def test_explicit_conflicting_publication_metadata_still_blocks_the_article(self):
        with self.assertRaises(ValueError):self.read(amd_page(original_clock="2026-11-03T22:15:00Z"))

    def test_modified_time_is_not_used_as_an_original_publication_clock(self):
        body = amd_page().replace('<article>', '<meta property="article:modified_time" content="2026-11-04T11:00:00Z"><article>')
        self.assertTrue(self.read(body))

    def test_upgrade_rechecks_the_old_failed_body_once_without_renewing_the_feed_clock(self):
        old = payload(AMD["url"],amd_rss(),release_excerpt_schema=3,release_evidence=[])
        fetch = Mock(return_value=payload(AMD_URL,amd_page()))
        new = originals.enrich_feed(AMD,old,feeds.parse_rss_items,fetch,READ_NOW)
        self.assertEqual(new["release_excerpt_schema"],4);fetch.assert_called_once_with(AMD_URL)
        self.assertEqual(new["fetched_at_epoch"],old["fetched_at_epoch"])
        self.assertEqual(new["release_evidence"][0]["published"],AMD_PUBLISHED)
        self.assertIs(originals.enrich_feed(AMD,new,feeds.parse_rss_items,fetch,READ_NOW),new)
        self.assertEqual(fetch.call_count,1)

    def test_a_real_conflict_remains_a_visible_limited_read_after_upgrade(self):
        old = payload(AMD["url"],amd_rss(),release_excerpt_schema=3)
        new = originals.enrich_feed(AMD,old,feeds.parse_rss_items,lambda url:payload(url,amd_page("04")),READ_NOW)
        self.assertFalse(new["release_evidence"])
        self.assertIn("does not match",new["release_read_reviews"][0]["reason"])


class NorthropChecks(unittest.TestCase):
    def retrieve(self, index="<main>Dynamic News Stream</main>", home=None, detail=None, **changes):
        values = {NORTHROP["url"]:payload(NORTHROP["url"],index),noc.HOME:payload(noc.HOME,noc_home() if home is None else home),
            NOC_URL:payload(NOC_URL,noc_page() if detail is None else detail)}
        values.update(changes)
        calls = []
        def fetch(url):
            calls.append(url)
            if url not in values:raise AssertionError("Unexpected publisher request: "+url)
            return deepcopy(values[url])
        return originals.retrieve(NORTHROP,fetch,READ_NOW),calls

    def test_empty_dynamic_stream_uses_the_one_configured_official_homepage(self):
        value,calls = self.retrieve()
        self.assertEqual(calls,[NORTHROP["url"],noc.HOME,NOC_URL])
        self.assertEqual(value["index_discovery_url"],noc.HOME)
        self.assertEqual(value["original_profile"],3)
        rows = originals.cached_items(value,NORTHROP)
        self.assertEqual(rows[0]["evidence_scope"],"original release excerpt")
        self.assertIn("synthetic test",rows[0]["description"])

    def test_existing_release_links_do_not_start_a_homepage_fallback(self):
        legacy_url = "https://news.northropgrumman.com/releases/synthetic-example-system"
        index = f'<a href="{legacy_url}">{NOC_TITLE}</a>'
        body = (f'<meta property="og:title" content="{NOC_TITLE}"><meta property="article:published_time" content="{NOC_PUBLISHED}">'
            f'<article><h1>{NOC_TITLE}</h1><p>A synthetic original article describes a navigation system and its planned testing program.</p></article>')
        value,calls = self.retrieve(index=index,**{legacy_url:payload(legacy_url,body)})
        self.assertEqual(calls,[NORTHROP["url"],legacy_url]);self.assertEqual(len(value["articles"]),1)

    def test_homepage_cards_are_deduplicated_and_generic_navigation_is_ignored(self):
        self.assertEqual(noc.home_items(noc_home()),[{"title":NOC_TITLE,"link":NOC_URL,"published":""}])
        self.assertFalse(noc.home_items('<a href="/media-contacts">Contacts</a><a href="/news-stream">News Stream</a>'))

    def test_foreign_and_unsafe_card_links_are_never_requested(self):
        for url in ("https://example.com/synthetic-release", "http://news.northropgrumman.com/example-news-release", "https://user@news.northropgrumman.com/example-news-release", NOC_URL+"?redirect=1"):
            self.assertFalse(noc.home_items(noc_home(url=url)))

    def test_truncated_or_conflicting_homepage_titles_do_not_become_article_candidates(self):
        self.assertFalse(noc.home_items(noc_home(title="A truncated headline…")))
        with self.assertRaises(ValueError):noc.home_items(noc_home()+noc_home(title="A different headline"))

    def test_homepage_discovery_is_limited_to_three_distinct_detail_pages(self):
        body = ''.join(noc_home(url=NOC_URL+str(i),title=NOC_TITLE+str(i)) for i in range(8))
        values = {NOC_URL+str(i):payload(NOC_URL+str(i),noc_page(title=NOC_TITLE+str(i),canonical=NOC_URL+str(i))) for i in range(3)}
        value,calls = self.retrieve(home=body,**values)
        self.assertEqual(len(value["articles"]),3);self.assertEqual(len(calls),5)

    def test_http_failure_of_the_primary_index_does_not_probe_a_fallback(self):
        failure = payload(NORTHROP["url"],status="error",error="HTTPError 403",http_status=403,retry_after_epoch=READ_NOW.timestamp()+3600)
        value,calls = self.retrieve(**{NORTHROP["url"]:failure})
        self.assertEqual(calls,[NORTHROP["url"]]);self.assertEqual(value["retry_after_epoch"],failure["retry_after_epoch"])

    def test_homepage_rate_limit_retains_the_publisher_retry_time(self):
        failure = payload(noc.HOME,status="error",error="HTTPError 429",http_status=429,retry_after_epoch=READ_NOW.timestamp()+900)
        value,calls = self.retrieve(**{noc.HOME:failure})
        self.assertEqual(value["status"],"error");self.assertEqual(value["retry_after_epoch"],failure["retry_after_epoch"])
        self.assertEqual(len(calls),2)

    def test_homepage_redirect_to_another_path_or_domain_is_rejected(self):
        for final in ("https://example.com/",noc.HOME+"news-stream"):
            with self.assertRaises(ValueError):self.retrieve(**{noc.HOME:payload(noc.HOME,noc_home(),final_url=final)})

    def test_stale_homepage_does_not_gain_a_fresh_index_observation(self):
        with self.assertRaises(ValueError):self.retrieve(**{noc.HOME:payload(noc.HOME,noc_home(),fetched_at_epoch=READ_NOW.timestamp()-7*3600)})

    def test_publication_uses_the_original_zoned_property_and_matching_identity(self):
        clock = publication_time(noc_page().encode(),NOC_TITLE,url=NOC_URL)
        self.assertEqual(clock,datetime(2026,11,4,10,tzinfo=timezone.utc))

    def test_publisher_double_leading_slash_canonical_reference_matches_only_the_same_page(self):
        canonical = NOC_URL.replace('.com/','.com//')
        self.assertEqual(publication_time(noc_page(canonical=canonical).encode(),NOC_TITLE,url=NOC_URL).hour,10)
        for wrong in (NOC_URL+"-different",NOC_URL.replace('news.northropgrumman.com','example.com')):
            with self.assertRaises(ValueError):publication_time(noc_page(canonical=wrong).encode(),NOC_TITLE,url=NOC_URL)

    def test_missing_naive_conflicting_and_modified_only_clocks_remain_held(self):
        for body in (noc_page(clock=""),noc_page(clock="2026-11-04T10:00:00"),
            noc_page(extra='<meta property="article:published_time" content="2026-11-04T11:00:00Z">'),
            noc_page().replace('og:publishDate','og:modifiedDate')):
            with self.assertRaises(ValueError):publication_time(body.encode(),NOC_TITLE,url=NOC_URL)

    def test_matching_date_cannot_rescue_a_different_or_duplicate_heading(self):
        for body in (noc_page().replace(f'<h1>{NOC_TITLE}</h1>','<h1>Different release</h1>'),noc_page()+f'<h1>{NOC_TITLE}</h1>'):
            with self.assertRaises(ValueError):publication_time(body.encode(),NOC_TITLE,url=NOC_URL)

    def test_article_body_excludes_media_contacts_and_uses_the_same_clock(self):
        text = originals.article_excerpt(noc_page(),NOC_TITLE,NOC_PUBLISHED,publisher=NORTHROP["name"],url=NOC_URL)
        self.assertIn("synthetic test program",text);self.assertNotIn("media contacts",text)

    def test_a_body_date_cannot_override_invalid_explicit_original_metadata(self):
        body = noc_page(clock="2026-11-04T10:00:00").replace("Northrop Grumman introduced", "November 4, 2026. Northrop Grumman introduced")
        with self.assertRaises(ValueError):
            originals.article_excerpt(body,NOC_TITLE,NOC_PUBLISHED,publisher=NORTHROP["name"],url=NOC_URL)

    def test_old_dated_articles_are_quiet_publisher_coverage(self):
        value,_ = self.retrieve(detail=noc_page(clock="2026-11-02T10:00:00Z"))
        health = feeds.describe_source(NORTHROP,value,READ_NOW)
        self.assertEqual(health["status"],"available");self.assertEqual(health["fresh"],0)
        self.assertIn("official newsroom homepage",health["reason"])

    def test_invalid_body_or_clock_does_not_make_available_publisher_coverage(self):
        value,_ = self.retrieve(detail=noc_page(clock="2026-11-04"))
        health = feeds.describe_source(NORTHROP,value,READ_NOW)
        self.assertEqual(health["status"],"limited");self.assertEqual(health["fresh"],0)

    def test_upgraded_reader_reprocesses_old_positive_cache_without_touching_http_cooldowns(self):
        old = payload(NORTHROP["url"],original_profile=2,articles=[])
        updated = {**old,"original_profile":3}
        with patch.object(feeds,"get_cached_source",return_value=old),patch.object(originals,"retrieve",return_value=updated) as read,patch.object(feeds,"set_cached_source"):
            self.assertEqual(feeds.fetch_source(NORTHROP)["original_profile"],3);self.assertEqual(read.call_count,1)
        failed = payload(NORTHROP["url"],status="error",error="HTTPError 403",retry_after_epoch=READ_NOW.timestamp()+3600)
        with patch.object(feeds,"get_cached_source",return_value=failed),patch.object(originals,"retrieve",side_effect=AssertionError("Cooldown must be respected")):
            self.assertEqual(feeds.fetch_source(NORTHROP,True)["retry_after_epoch"],failed["retry_after_epoch"])


class NarrationChecks(IsolatedChecks):
    def setUp(self):
        super().setUp()
        ranks = json.loads(self.ranking.read_text());ranks["current"]["CACI"] = {"opportunity_score":82,"structural_score":80}
        self.ranking.write_text(json.dumps(ranks))

    def render(self):
        with patch.object(editor,"cache_candidates",return_value=([source(),source("CACI"),source("EIA")],[])):
            report = build_daily_news_brief(self.research())
        return report,store.read_editions(report=report)[0]

    def test_new_contract_copy_speaks_the_value_after_the_award_noun(self):
        report,record = self.render();profile = voice.checked(record,NOW)
        self.assertIn("contract award from the U S Air Force worth sixty four million dollars",profile["script"])
        self.assertNotIn("million dollars contract award",profile["script"])
        self.assertIn("$64 million contract award",report)

    def test_energy_observation_has_an_energy_transition_and_agency_name(self):
        _,record = self.render();profile = voice.checked(record,NOW)
        scene = next(row for row in profile["segments"] if row["heading"] == "Energy Watch")
        self.assertTrue(scene["narration"].startswith("In energy. The U S Energy Information Administration reported"))
        self.assertNotIn("On policy",scene["narration"])
        self.assertIn("second quarter of",scene["narration"])

    def test_source_references_review_requirement_and_schema2_remain_intact(self):
        _,record = self.render();episode = voice.episode(record,NOW)
        self.assertEqual(record["rules_version"],22);self.assertEqual(episode["voiceover_schema"],2)
        self.assertTrue(episode["review_required"]);self.assertEqual(episode["mode"],"draft_review_required")
        used = {key for scene in episode["segments"] for key in scene["source_ids"]}
        self.assertEqual(used,set(episode["sources"]))

    def test_rules21_saved_edition_keeps_its_original_brief_and_voiceover_hashes(self):
        record = json.loads((ROOT/"scripts/fixtures/publisher_rules21_edition.json").read_text())
        profile = voice.checked(record,NOW)
        self.assertEqual(record["rules_version"],21)
        self.assertEqual(record["report_sha256"],"1910597b7b430b29dc5556c6400405a9f8a8ff2547bca05c458c5e9845a8993b")
        self.assertEqual(profile["script_sha256"],"7c809d29fae36aea9807a91a463ba8baed755f89db4ecb7af41446b70fc5db51")
        self.assertIn("On policy. EIA",profile["script"])
        self.assertIn("million dollars contract award",profile["script"])

    def test_default_speech_normalization_keeps_historical_agency_copy(self):
        self.assertEqual(normalize("EIA reported a change."),"EIA reported a change.")
        self.assertEqual(normalize("EIA reported a change.",agency_names=True),"The U S Energy Information Administration reported a change.")
        self.assertIn("to the U S Energy Information Administration",normalize("According to EIA, the figures changed.",agency_names=True))


def main():
    parser = argparse.ArgumentParser();parser.add_argument("--windows-socketpair",action="store_true");args = parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair:stack.enter_context(patch.object(socket,"socketpair",portable_tcp_socketpair))
        traffic = stack.enter_context(offline_network_guard())
        # Imported fixture classes are helpers, not part of this suite.
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls) for cls in [AMDChecks,NorthropChecks,NarrationChecks])
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    passed = result.wasSuccessful() and not traffic["blocked"]
    print(f"Publisher Reader Check: {'PASS' if passed else 'FAIL'} ({result.testsRun} tests)")
    return 0 if passed else 1


if __name__ == "__main__":raise SystemExit(main())
