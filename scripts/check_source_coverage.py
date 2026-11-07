"""Offline source recovery, contact setup and saved-edition regression checks."""

import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from html import escape
import io
import json
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_daily_news_brief import IsolatedChecks, NOW
from scripts.check_disclosure_details import maintenance, sanctions
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from scripts import configure_sec_contact as setup
from src.intelligence import publisher_recovery as reader, news_live_sources as feeds, news_original_sources as originals
from src.intelligence import sec_contact as contact, alphabet_earnings as alphabet, hourly_research as desk
from src.intelligence import news_editor as editor, news_editor_store as store
from src.reports import daily_voiceover as voice
from src.reports.daily_news_brief import build_daily_news_brief, validate_news_brief

STAMP = (NOW-timedelta(minutes=20)).isoformat()
TEXT = "Eaton reported third quarter 2026 sales of $2.3 billion, up 8 percent year over year. The company expects fourth quarter sales growth of 6 to 8 percent. This is synthetic test evidence, not a real release."
TITLES = {"ETN": "Eaton reports third quarter results and updates its business outlook",
          "CRWD": "CrowdStrike announces a new enterprise security platform with customer trials"}
URLS = {symbol: reader.SOURCES[symbol][0].replace("news-insights.html", "news-insights/news-releases/2026/synthetic-results.html")
        if symbol == "ETN" else reader.SOURCES[symbol][0]+"synthetic-new-platform/" for symbol in reader.SOURCES}


def source(symbol="ETN"):
    return next(row for row in feeds.NEWS_SOURCES if row.get("company_symbol") == symbol and row.get("format") == "corporate")


def payload(url, body="", **changes):
    return {"url": url, "final_url": url, "status": "ok", "body": body, "fetched_at_epoch": NOW.timestamp(), **changes}


def page(symbol="ETN", *, url=None, clock=STAMP, title=None, text=TEXT, metadata=None, extra=""):
    url, title = url or URLS[symbol], title or TITLES[symbol]
    short = title if symbol == "ETN" else title.rsplit(" with ", 1)[0]
    meta = ({"@type": "Article", "headline": title, "mainEntityOfPage": {"@id":url}, "datePublished": clock}
            if symbol == "ETN" else {"@type":"WebPage", "@id":url+"#webpage", "name":short, "datePublished":clock,
                                      "dateModified":NOW.isoformat()})
    if metadata is not None:
        meta = metadata
    classes = "eaton-text-default__content overlapping__anchor" if symbol == "ETN" else "text--press-release-content"
    return (f'<meta property="og:title" content="{escape(short)}"><meta property="og:url" content="{url}">'
            f'<link rel="canonical" href="{url}"><script type="application/ld+json">{json.dumps(meta)}</script>'
            f'<nav><article>Unrelated supplier award for $9 billion.</article></nav><h1>{escape(title)}</h1>'
            f'<div class="{classes}"><p>{escape(text)}</p></div>'
            '<footer><div class="eaton-text-default__content">Footer is not the original disclosure.</div></footer>'+extra)


def retrieved(symbol="ETN", pages=None, index=None):
    route = source(symbol)
    calls = []
    index = index if index is not None else f'<a href="{URLS[symbol]}">Short listing title</a>'
    values = {route["url"]:payload(route["url"],index), URLS[symbol]:payload(URLS[symbol],page(symbol))}
    values.update(pages or {})
    def fetch(url):
        calls.append(url)
        if url not in values:
            raise AssertionError("Unbounded or unconfigured request: "+url)
        return values[url]
    return reader.retrieve(route, fetch, NOW), calls


class PublicationChecks(unittest.TestCase):
    def test_eaton_uses_complete_original_headline_body_and_clock(self):
        result,calls = retrieved()
        row = originals.cached_items(result,source())[0]
        self.assertEqual(row["title"],TITLES["ETN"])
        self.assertEqual(row["description"],TEXT)
        self.assertEqual(row["published"],STAMP)
        self.assertEqual(row["evidence_scope"],"original release excerpt")
        self.assertEqual(calls,[source()["url"],URLS["ETN"]])

    def test_crowdstrike_binds_short_metadata_name_and_full_h1_to_exact_url(self):
        result,_ = retrieved("CRWD")
        row = originals.cached_items(result,source("CRWD"))[0]
        self.assertEqual(row["title"],TITLES["CRWD"])
        self.assertEqual(row["published"],STAMP)

    def test_exact_crowdstrike_site_suffix_is_separate_from_the_complete_headline(self):
        short=TITLES["CRWD"].rsplit(" with ",1)[0]
        body=page("CRWD").replace(short+'"',short+' | CrowdStrike"')
        row=reader.page_article("CRWD",URLS["CRWD"],body,NOW,NOW.timestamp())
        self.assertEqual(row["title"],TITLES["CRWD"])
        reader.checked_article("CRWD",row,NOW)

    def test_an_unknown_site_suffix_is_not_stripped(self):
        short=TITLES["CRWD"].rsplit(" with ",1)[0]
        body=page("CRWD").replace(short+'"',short+' | Other Publisher"')
        with self.assertRaises(ValueError):reader.page_article("CRWD",URLS["CRWD"],body,NOW,NOW.timestamp())

    def test_conflicting_crowdstrike_metadata_url_is_rejected(self):
        short=TITLES["CRWD"].rsplit(" with ",1)[0]
        meta={"@type":"WebPage","@id":URLS["CRWD"]+"#webpage","name":short,"datePublished":STAMP,"url":"https://example.com/wrong"}
        with self.assertRaises(ValueError):reader.page_article("CRWD",URLS["CRWD"],page("CRWD",metadata=meta),NOW,NOW.timestamp())

    def test_date_only_or_naive_original_clock_cannot_become_fresh_news(self):
        for clock in ("2026-10-25", "2026-10-25Z", "2026-10-25T16:40:00", ""):
            with self.subTest(clock=clock), self.assertRaises(ValueError):
                reader.page_article("ETN",URLS["ETN"],page(clock=clock),NOW,NOW.timestamp())

    def test_updated_timestamp_is_not_an_original_publication(self):
        meta={"@type":"Article","headline":TITLES["ETN"],"mainEntityOfPage":{"@id":URLS["ETN"]},"dateModified":STAMP}
        with self.assertRaises(ValueError):
            reader.page_article("ETN",URLS["ETN"],page(metadata=meta),NOW,NOW.timestamp())

    def test_other_article_metadata_cannot_date_this_release(self):
        meta={"@type":"Article","headline":TITLES["ETN"],"mainEntityOfPage":{"@id":URLS["ETN"]+"wrong"},"datePublished":STAMP}
        with self.assertRaises(ValueError):
            reader.page_article("ETN",URLS["ETN"],page(metadata=meta),NOW,NOW.timestamp())

    def test_conflicting_original_publication_fields_are_rejected(self):
        extra=f'<meta property="article:published_time" content="{NOW.isoformat()}">'
        with self.assertRaises(ValueError):
            reader.page_article("ETN",URLS["ETN"],page(extra=extra),NOW,NOW.timestamp())

    def test_two_conflicting_bound_json_clocks_are_rejected(self):
        body=page()+f'<script type="application/ld+json">{json.dumps({"@type":"Article","headline":TITLES["ETN"],"mainEntityOfPage":{"@id":URLS["ETN"]},"datePublished":NOW.isoformat()})}</script>'
        with self.assertRaises(ValueError):reader.page_article("ETN",URLS["ETN"],body,NOW,NOW.timestamp())

    def test_duplicate_or_wrong_original_headline_is_rejected(self):
        for body in (page()+f'<h1>{TITLES["ETN"]}</h1>',page().replace(TITLES["ETN"]+"</h1>","Different article</h1>")):
            with self.assertRaises(ValueError):reader.page_article("ETN",URLS["ETN"],body,NOW,NOW.timestamp())

    def test_source_navigation_and_footer_never_supply_article_facts(self):
        row=reader.page_article("ETN",URLS["ETN"],page(),NOW,NOW.timestamp())
        self.assertNotIn("supplier",row["description"]);self.assertNotIn("Footer",row["description"])

    def test_a_generic_article_tag_does_not_replace_the_publisher_body(self):
        body=page().replace("eaton-text-default__content overlapping__anchor","unidentified-layout")
        with self.assertRaises(ValueError):reader.page_article("ETN",URLS["ETN"],body,NOW,NOW.timestamp())

    def test_missing_short_or_future_article_is_not_admitted(self):
        for body,observed in ((page(text="Short."),NOW.timestamp()),(page(clock=(NOW+timedelta(hours=1)).isoformat()),NOW.timestamp()),(page(),NOW.timestamp()-21601)):
            with self.assertRaises(ValueError):reader.page_article("ETN",URLS["ETN"],body,NOW,observed)

    def test_new_reader_is_limited_to_three_unique_release_reads(self):
        urls=[URLS["ETN"].replace("synthetic-results",f"synthetic-{i}") for i in range(8)]
        index=''.join(f'<a href="{url}">Listing</a><a href="{url}">Duplicate</a>' for url in urls)
        values={url:payload(url,page(url=url)) for url in urls[:3]}
        result,calls=retrieved(pages=values,index=index)
        self.assertEqual(calls,[source()["url"]]+urls[:3]);self.assertEqual(len(result["articles"]),3)

    def test_foreign_insecure_query_and_traversal_links_are_not_requested(self):
        for url in (URLS["ETN"]+"?redirect=1",URLS["ETN"]+"#fragment",URLS["ETN"].replace("https:","http:"),URLS["ETN"].replace("www.eaton.com","www.eaton.com.attacker.test"),URLS["ETN"].replace("https://","https://user@")):
            self.assertFalse(reader.article_url("ETN",url))
        with self.assertRaises(ValueError):retrieved(index='<a href="https://example.com/release">Foreign</a>')

    def test_redirect_to_another_same_publisher_article_is_rejected(self):
        value=payload(URLS["ETN"],page(),final_url=URLS["ETN"].replace("synthetic-results","different"))
        result,_=retrieved(pages={URLS["ETN"]:value})
        self.assertEqual(result["articles"][0]["published"],"")
        self.assertEqual(result["release_read_reviews"][0]["status"],"limited")

    def test_canonical_cannot_bind_a_different_url(self):
        body=page().replace('rel="canonical" href="'+URLS["ETN"], 'rel="canonical" href="https://example.com/wrong')
        with self.assertRaises(ValueError):reader.page_article("ETN",URLS["ETN"],body,NOW,NOW.timestamp())

    def test_primary_403_keeps_its_cooldown_without_probing_details(self):
        route=source();failure=payload(route["url"],status="error",error="HTTPError 403",retry_after_epoch=NOW.timestamp()+3600)
        calls=[]
        result=reader.retrieve(route,lambda url:(calls.append(url) or failure),NOW)
        self.assertEqual(calls,[route["url"]]);self.assertEqual(result,failure)

    def test_cached_article_text_identity_and_clocks_cannot_be_changed(self):
        result,_=retrieved()
        for field in ("description","title","link","published","evidence_checked_at"):
            changed=deepcopy(result);changed["articles"][0][field]="tampered"
            with self.subTest(field=field),self.assertRaises(ValueError):originals.cached_items(changed,source())

    def test_previous_generic_cache_profile_cannot_replace_corporate_proof(self):
        result,_=retrieved();result["original_profile"]=2
        with self.assertRaises(ValueError):originals.cached_items(result,source())

    def test_live_refresh_dispatches_the_configured_corporate_reader(self):
        route=source();values={route["url"]:payload(route["url"],f'<a href="{URLS["ETN"]}">Short title</a>'),URLS["ETN"]:payload(URLS["ETN"],page())}
        with patch.object(feeds,"get_cached_source",return_value=None),patch.object(feeds,"fetch_url",side_effect=lambda url,*a,**k:values[url]),patch.object(feeds,"set_cached_source"),patch.object(feeds,"datetime") as clock:
            clock.now.return_value=NOW
            result=feeds.fetch_source(route,True)
        self.assertEqual(result["original_profile"],5)
        self.assertEqual(originals.cached_items(result,route)[0]["title"],TITLES["ETN"])

    def test_force_refresh_cannot_override_a_corporate_http_cooldown(self):
        route=source();failure=payload(route["url"],status="error",error="HTTPError 429",retry_after_epoch=NOW.timestamp()+900)
        with patch.object(feeds,"get_cached_source",return_value=failure),patch.object(feeds,"fetch_url") as fetch:
            result=feeds.fetch_source(route,True)
        fetch.assert_not_called();self.assertEqual(result["retry_after_epoch"],failure["retry_after_epoch"])

    def test_body_read_with_old_publication_is_dated_context_not_fresh_news(self):
        result,_=retrieved(pages={URLS["ETN"]:payload(URLS["ETN"],page(clock=(NOW-timedelta(days=3)).isoformat()))})
        health=feeds.describe_source(source(),result,NOW)
        self.assertEqual(health["fresh"],0);self.assertEqual(health["fresh_bodies"],0)
        self.assertEqual(health["evidence_level"],"dated original body")

    def test_verified_body_health_keeps_failed_ir_route_separate(self):
        result,_=retrieved("CRWD")
        good=feeds.describe_source(source("CRWD"),result,NOW)
        ir=next(s for s in feeds.NEWS_SOURCES if s["name"]=="CrowdStrike Investor Relations")
        bad=feeds.describe_source(ir,payload(ir["url"],status="error",error="HTTPError 403"),NOW)
        summary=feeds.coverage_summary([good,bad])
        self.assertEqual(bad["status"],"limited");self.assertEqual(good["evidence_level"],"fresh original body")
        self.assertIn("1/2 available",summary);self.assertIn("1/1 companies",summary)

    def test_reachable_feed_with_no_body_is_labeled_a_dated_listing(self):
        route=next(s for s in feeds.NEWS_SOURCES if s.get("company_symbol")=="MSFT")
        body=f'<rss><channel><item><title>Microsoft synthetic current business report</title><link>https://blogs.microsoft.com/synthetic-release</link><pubDate>{STAMP}</pubDate></item></channel></rss>'
        health=feeds.describe_source(route,payload(route["url"],body),NOW)
        self.assertEqual(health["status"],"available");self.assertEqual(health["evidence_level"],"dated listing")
        self.assertEqual(health["fresh_bodies"],0)

    def test_stale_cache_is_unavailable_even_if_it_contains_body_evidence(self):
        result,_=retrieved();result["fetched_at_epoch"]=NOW.timestamp()-21601
        health=feeds.describe_source(source(),result,NOW)
        self.assertEqual(health["evidence_level"],"unavailable");self.assertEqual(health["fresh_bodies"],0)


class ContactChecks(unittest.TestCase):
    def test_header_needs_an_application_and_one_nonplaceholder_contact(self):
        self.assertTrue(contact.valid_user_agent("Offline Fixture admin@fixture.test"))
        for value in ("", "SmartMoneyAI", "admin@fixture.test", "Your Name your-email@example.com", "Bot contact@example.org", "Bot a@fixture.test\nInjected:1", "Bot a@fixture.test b@fixture.test", "Bot a@fixture.test$SECRET"):
            with self.subTest(value=value):self.assertFalse(contact.valid_user_agent(value))

    def test_valid_alias_is_used_when_primary_is_absent_or_invalid(self):
        values={"SEC_USER_AGENT":"invalid","SEC_API_USER_AGENT":"Offline Fixture admin@fixture.test"}
        self.assertEqual(contact.user_agent(values),values["SEC_API_USER_AGENT"])

    def test_local_configuration_errors_can_be_rechecked_without_clearing_http_cooldowns(self):
        base={"status":"error","error":contact.MESSAGE,"fetched_at_epoch":NOW.timestamp(),"retry_after_epoch":NOW.timestamp()+3600}
        with patch.object(feeds.time,"time",return_value=NOW.timestamp()),patch.object(feeds,"load_cache",return_value={alphabet.SUBMISSIONS:base}):
            self.assertIsNone(feeds.get_cached_source(alphabet.SUBMISSIONS))
        base={**base,"error":"HTTPError 403","http_status":403}
        with patch.object(feeds.time,"time",return_value=NOW.timestamp()),patch.object(feeds,"load_cache",return_value={alphabet.SUBMISSIONS:base}):
            self.assertEqual(feeds.get_cached_source(alphabet.SUBMISSIONS),base)

    def test_alphabet_missing_contact_makes_no_request(self):
        with patch.dict(os.environ,{"SEC_USER_AGENT":"invalid","SEC_API_USER_AGENT":""}),patch.object(feeds,"get_cached_source",return_value=None),patch.object(feeds,"load_cache",return_value={}),patch.object(feeds,"set_cached_source"),patch.object(feeds,"fetch_url") as fetch:
            result=alphabet.refresh(True)
        fetch.assert_not_called();self.assertIn("configure_sec_contact.py",result["error"])

    def test_hourly_sec_reader_checks_contact_before_any_request(self):
        with patch.dict(os.environ,{"SEC_USER_AGENT":"invalid","SEC_API_USER_AGENT":""}),patch('src.intelligence.hourly_research.build_opener') as opener:
            with self.assertRaisesRegex(ValueError,"SEC_USER_AGENT"):
                desk.fetch_original("https://data.sec.gov/submissions/CIK0001652044.json")
        opener.assert_not_called()

    def path(self,folder,raw=b"BOT_OTHER='keep exactly'\n"):
        path=Path(folder)/".env";path.write_bytes(raw);path.chmod(0o640);return path

    def test_existing_valid_contact_is_preserved_without_prompt_or_write(self):
        with tempfile.TemporaryDirectory() as folder:
            path=self.path(folder,b"SEC_USER_AGENT='Offline Fixture admin@fixture.test'\nOTHER=abc\n")
            original=path.read_bytes()
            result=setup.configure(path,prompt=lambda _:self.fail("Unnecessary contact prompt"))
            self.assertEqual(path.read_bytes(),original);self.assertEqual(len(list(Path(folder).iterdir())),1)
            self.assertNotIn("admin@",result)

    def test_setup_preserves_other_settings_bom_crlf_owner_mode_and_private_backup(self):
        raw=b"\xef\xbb\xbfBOT_OTHER='keep exactly'\r\nSEC_USER_AGENT='placeholder'\r\nTAIL=last"
        with tempfile.TemporaryDirectory() as folder:
            path=self.path(folder,raw);before=path.stat()
            result=setup.configure(path,prompt=lambda _:"admin@fixture.test")
            value=path.read_bytes()
            self.assertTrue(value.startswith(b"\xef\xbb\xbf"));self.assertIn(b"BOT_OTHER='keep exactly'\r\n",value)
            self.assertIn(b"TAIL=last",value);self.assertEqual(stat.S_IMODE(path.stat().st_mode),stat.S_IMODE(before.st_mode))
            self.assertEqual(path.stat().st_uid,before.st_uid)
            backup=next(Path(folder).glob('.env.sec-contact-backup-*'))
            self.assertEqual(backup.read_bytes(),raw)
            if os.name != "nt":self.assertEqual(stat.S_IMODE(backup.stat().st_mode),0o600)
            self.assertNotIn("admin@fixture.test",result)

    def test_missing_key_is_added_once_and_next_setup_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            path=self.path(folder)
            setup.configure(path,prompt=lambda _:"admin@fixture.test")
            raw=path.read_bytes();setup.configure(path,prompt=lambda _:self.fail("Unexpected prompt"))
            self.assertEqual(path.read_bytes(),raw);self.assertEqual(raw.count(b"SEC_USER_AGENT="),1)

    def test_invalid_contact_does_not_change_or_backup_the_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            path=self.path(folder);before=path.read_bytes()
            with self.assertRaises(ValueError):setup.configure(path,prompt=lambda _:"your-email@example.com")
            self.assertEqual(path.read_bytes(),before);self.assertEqual(len(list(Path(folder).iterdir())),1)

    def test_duplicate_keys_need_local_review_before_prompting(self):
        with tempfile.TemporaryDirectory() as folder:
            path=self.path(folder,b"SEC_USER_AGENT=x\nexport SEC_USER_AGENT=y\n")
            with self.assertRaisesRegex(ValueError,"Duplicate"):setup.configure(path,prompt=lambda _:self.fail("Unexpected prompt"))

    def test_symlink_environment_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=self.path(folder);link=Path(folder)/"link.env"
            try:link.symlink_to(path)
            except (OSError,NotImplementedError):self.skipTest("Account cannot create symbolic links")
            with self.assertRaisesRegex(ValueError,"regular file"):setup.configure(link,prompt=lambda _:self.fail("Unexpected prompt"))

    def test_concurrent_environment_edit_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path=self.path(folder)
            def change(_):
                path.write_text("OTHER=concurrent\n")
                return "admin@fixture.test"
            with self.assertRaisesRegex(ValueError,"changed during"):setup.configure(path,prompt=change)
            self.assertEqual(path.read_text(),"OTHER=concurrent\n")
            self.assertFalse(list(Path(folder).glob('.sec-contact-*')))

    def test_replacement_failure_keeps_original_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            path=self.path(folder);before=path.read_bytes()
            with patch.object(setup.os,"replace",side_effect=OSError("Synthetic failure")),self.assertRaises(OSError):
                setup.configure(path,prompt=lambda _:"admin@fixture.test")
            self.assertEqual(path.read_bytes(),before)

    def test_check_does_not_prompt_or_write(self):
        with tempfile.TemporaryDirectory() as folder:
            path=self.path(folder);before=path.read_bytes()
            with self.assertRaises(ValueError):setup.configure(path,check=True,prompt=lambda _:self.fail("Unexpected prompt"))
            self.assertEqual(path.read_bytes(),before)


class EditionChecks(IsolatedChecks):
    def render(self, rows):
        with patch.object(editor,"cache_candidates",return_value=(rows,[])):
            report=build_daily_news_brief(self.research())
        return report,store.read_editions(report=report)[0]

    def test_new_edition_retains_facts_and_tells_full_maintenance_details_once(self):
        report,record=self.render([maintenance(),sanctions()])
        self.assertEqual(record["rules_version"],29)
        self.assertEqual(record["analyst_review"]["disclosure_version"],2)
        self.assertTrue(validate_news_brief(report)["passes"])
        self.assertEqual(sum(len(s["event_evidence"]["facts"]) for s in editor.selected_stories(record)),8)
        self.assertEqual(report.count("said its Example Bay, Louisiana facility was selected"),1)
        self.assertIn("disclosed service-order value and delivery timetable",report)
        self.assertNotIn("Watch for maintenance orders, site utilization, staffing costs and revenue timing.",report)
        script=voice.checked(record,NOW)["script"]
        self.assertEqual(script.count("said its Example Bay, Louisiana facility was selected"),1)
        self.assertIn("C one thirty Hercules",script)

    def test_source_recovered_candidates_keep_their_original_clocks_and_scope(self):
        result,_=retrieved()
        with patch.object(feeds,"NEWS_SOURCES",[source()]):
            rows,issues=editor.cache_candidates(NOW,["ETN"],cache={source()["url"]:result})
        self.assertFalse(issues);self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["published"],STAMP);self.assertEqual(rows[0]["publisher_symbol"],"ETN")
        self.assertEqual(rows[0]["excerpt_scope"],"original release excerpt")
        report,record=self.render(rows)
        selected=editor.selected_stories(record)
        self.assertEqual(len(selected),1)
        self.assertEqual(selected[0]["event_evidence"]["source_text"],TEXT)
        self.assertTrue(validate_news_brief(report)["passes"])

    def test_saved_rules27_report_script_and_schema2_export_are_unchanged(self):
        record=json.loads((ROOT/'scripts/fixtures/disclosure_rules27_edition.json').read_text())
        self.assertEqual(record["report_sha256"],"17c88400ca87eacf38d424b2051983a35cb2e202252f4a65872be38c9bf9e2cf")
        self.assertEqual(voice.checked(record,NOW)["script_sha256"],"6914505b5a9bafec59063be389c708c0394365a2c7d0365cf4b657ae6b88270f")
        self.assertEqual(voice.episode(record,NOW)["voiceover_sha256"],record["voiceover"]["script_sha256"])

    def test_current_editorstatus_distinguishes_body_and_ir_health(self):
        result,_=retrieved("CRWD")
        with patch.object(feeds,"NEWS_SOURCES",[source("CRWD")]),patch.object(feeds,"CACHE_FILE",self.root/'news.json'):
            feeds.set_cached_source(source("CRWD")["url"],result)
            with patch.object(editor,"cache_candidates",wraps=editor.cache_candidates):
                report=build_daily_news_brief(self.research())
            status=editor.build_editor_status()
        self.assertIn("evidence: fresh original body",status);self.assertIn("Issuer coverage:",status)


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--windows-socketpair",action="store_true");args=parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair:stack.enter_context(patch.object(socket,"socketpair",portable_tcp_socketpair))
        traffic=stack.enter_context(offline_network_guard())
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(case) for case in (PublicationChecks,ContactChecks,EditionChecks))
        result=unittest.TextTestRunner(verbosity=1).run(suite)
    good=result.wasSuccessful() and not traffic["blocked"]
    print(f"Source Coverage Check: {'PASS' if good else 'FAIL'} ({result.testsRun} tests)")
    return 0 if good else 1


if __name__=='__main__':raise SystemExit(main())
