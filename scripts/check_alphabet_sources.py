"""Offline contracts for original Alphabet releases and the investor handoff."""

from contextlib import ExitStack
from copy import deepcopy
from datetime import timedelta
from email.utils import format_datetime
import argparse
import json
import os
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_daily_news_brief import NOW
from scripts.check_hourly_research import ResearchFixture, Client
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from src.intelligence import alphabet_source as alphabet, news_editor as editor, news_editor_store as store
from src.intelligence import news_live_sources as feeds, hourly_research as desk
from src.intelligence.story_analysis import build_evidence, checked_evidence
from src.reports.daily_news_brief import build_daily_news_brief, validate_news_brief

TITLE = "Alphabet Announces Third Quarter 2026 Results"
URL = "https://abc.xyz/investor/news/news-details/2026/Alphabet-Announces-Third-Quarter-2026-Results-2026-Fixture/default.aspx"
PDF = "https://s206.q4cdn.com/479360582/files/doc_news/2026/Oct/25/attachments/2026q3-alphabet-earnings-release.pdf"
QUOTE = "Consolidated Alphabet revenues increased 25% to $12.5 billion."


def pdf(lines):
    def literal(value): return value.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    stream = ('BT /F1 10 Tf 40 760 Td\n' + '\n'.join('('+literal(line)+') Tj 0 -14 Td' for line in lines) + '\nET').encode('latin1')
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
        b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream', b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    raw = b'%PDF-1.4\n'; offsets = [0]
    for i, value in enumerate(objects, 1):
        offsets.append(len(raw)); raw += str(i).encode()+b' 0 obj\n'+value+b'\nendobj\n'
    start = len(raw); raw += b'xref\n0 6\n0000000000 65535 f \n'
    raw += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    return raw + f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()


def earnings_pdf(**changes):
    lines = [changes.get('title', TITLE), 'MOUNTAIN VIEW, Calif. - October 25, 2026 - Alphabet Inc. (NASDAQ: GOOG, GOOGL)',
        'today announced financial results for the quarter ended September 30, 2026.', QUOTE,
        'Consolidated Alphabet operating income increased and operating margin was 31.8%.',
        'Net income available to common stockholders was $2.6 billion and EPS was $2.12.',
        'Sundar Pichai, CEO, said: We continue to invest in the business.']
    if changes.get('date'): lines[1] = lines[1].replace('October 25, 2026', changes['date'])
    return pdf(lines)


class AlphabetChecks(ResearchFixture):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"SPECIAL_ALERT_SYMBOLS": "GOOGL,MSFT,NVDA,TSM"}))
        self.stack.enter_context(patch.object(feeds, 'CACHE_FILE', self.root / 'news.json'))
        self.source = next(row for row in feeds.NEWS_SOURCES if row.get("format") == "alphabet")

    def rss(self, *, title=TITLE, url=URL, published=None):
        return ('<rss><channel><item><title>'+escape(title)+'</title><link>'+escape(url)+'</link><pubDate>'
                +escape(published if published is not None else format_datetime(NOW-timedelta(minutes=20)))+'</pubDate></item></channel></rss>')

    def page(self, *, title=TITLE, date="October 25, 2026", attachment=PDF, body="", metadata=""):
        return (metadata+'<h3>'+escape(title)+'</h3><span class="evergreen-news-date-text">'+date+'</span>'
                +('<div class="evergreen-news-body">'+body+'</div>' if body else '')+'<a href="'+attachment+'">Results PDF</a>')

    def raw(self, url):
        return self.rss().encode() if url == alphabet.FEED else self.page().encode() if url == URL else earnings_pdf() if url == PDF else None

    def payload(self, url, body):
        return {"status": "ok", "url": url, "final_url": url, "body": body, "fetched_at_epoch": NOW.timestamp()}

    def retrieve(self, overrides=None):
        overrides = overrides or {}; calls = []
        def fetch(url):
            calls.append(url)
            value = overrides.get(url, self.raw(url))
            if isinstance(value, dict): return value
            return self.payload(url, value if url == PDF else value.decode())
        result = alphabet.retrieve(self.source, fetch, NOW)
        return result, calls

    def seed(self, payload=None):
        payload = payload or self.retrieve()[0]
        Path(os.environ['NEWS_LIVE_SOURCE_CACHE_FILE']).write_text(json.dumps({alphabet.FEED: payload}))
        return payload

    def test_original_rss_and_linked_pdf_supply_dated_report_text_with_three_reads(self):
        payload, calls = self.retrieve()
        self.assertEqual(calls, [alphabet.FEED, URL, PDF])
        row = feeds.parse_article_items(payload, self.source, full_titles=True, full_text=True)[0]
        self.assertIn(QUOTE, row['description'])
        self.assertEqual(row['document_url'], PDF)
        self.assertEqual(row['published'], format_datetime(NOW-timedelta(minutes=20)))
        self.assertEqual(row['evidence_scope'], 'original release excerpt')

    def test_one_issuer_reader_covers_both_share_classes(self):
        self.seed(); brief = editor.build_editorial_plan({'rows':[{'symbol':'GOOGL','events':[]}], 'issues':[]}, NOW)
        self.assertEqual(len(editor.selected_stories(brief)), 1)
        self.assertEqual(editor.selected_stories(brief)[0]['publisher_symbol'], 'GOOG')
        self.assertFalse(any(row['symbol'] in {'GOOG','GOOGL'} and row['reason']=='Direct publisher reader not configured' for row in brief['source_health']))

    def test_readable_original_results_enter_the_brief_with_period_specific_figures(self):
        self.seed(); text = build_daily_news_brief(self.research())
        self.assertIn(TITLE, text)
        self.assertIn('$12.5 billion (third quarter 2026)', text)
        self.assertIn('31.8% (third quarter 2026)', text)
        self.assertIn('$2.12 (third quarter 2026)', text)
        self.assertTrue(validate_news_brief(text)['passes'])
        story = editor.selected_stories(store.read_editions(report=text)[0])[0]
        self.assertEqual(story['document_url'], PDF)
        self.assertEqual(story['event_evidence']['schema'], 5)
        self.assertEqual(len(checked_evidence(story)['facts']), 3)

    def test_report_rendering_reads_the_cache_without_source_fetches(self):
        self.seed(); before = Path(os.environ['NEWS_LIVE_SOURCE_CACHE_FILE']).read_bytes()
        with patch.object(alphabet, 'retrieve', side_effect=AssertionError('No source fetch while rendering')):
            text = build_daily_news_brief(self.research())
        self.assertIn(TITLE, text)
        self.assertEqual(Path(os.environ['NEWS_LIVE_SOURCE_CACHE_FILE']).read_bytes(), before)

    def test_blocked_document_remains_limited_and_does_not_publish_the_headline(self):
        payload, _ = self.retrieve({PDF:{'status':'error','error':'HTTP 403','fetched_at_epoch':NOW.timestamp()}})
        self.assertEqual(feeds.describe_source(self.source, payload, NOW)['status'], 'limited')
        self.seed(payload); text = build_daily_news_brief(self.research())
        self.assertNotIn(TITLE, text)
        self.assertNotIn('$12.5 billion', text)

    def test_other_cdn_tenants_and_unlinked_documents_are_not_fetched(self):
        for url in (PDF.replace('479360582','000000000'), PDF.replace('s206.q4cdn.com','attacker.test'), PDF+'?redirect=elsewhere', PDF.replace('2026q3','2026q2')):
            payload, calls = self.retrieve({URL:self.page(attachment=url).encode()})
            self.assertEqual(calls, [alphabet.FEED, URL])
            self.assertFalse(payload['articles'][0]['release_body_verified'])

    def test_changed_release_heading_or_visible_date_cannot_bind_the_pdf(self):
        for body in (self.page(title='Unrelated company results'), self.page(date='October 24, 2026')):
            payload, calls = self.retrieve({URL:body.encode()})
            self.assertEqual(calls, [alphabet.FEED, URL])
            self.assertTrue(payload['publication_problems'])

    def test_document_title_or_date_must_match_the_release(self):
        for body in (earnings_pdf(title='Alphabet Announces Second Quarter 2026 Results'), earnings_pdf(date='October 24, 2026')):
            payload, _ = self.retrieve({PDF:body})
            self.assertFalse(payload['articles'][0]['release_body_verified'])

    def test_redirected_attachment_cannot_supply_original_evidence(self):
        value = self.payload(PDF, earnings_pdf()); value['final_url'] = 'https://attacker.test/results.pdf'
        payload, _ = self.retrieve({PDF:value})
        self.assertTrue(payload['publication_problems'])

    def test_invalid_or_oversized_pdf_is_held_without_replacing_a_publication_clock(self):
        for body in (b'<html>not a PDF</html>', b'%PDF-'+b'x'*2_000_000):
            payload, _ = self.retrieve({PDF:body})
            self.assertFalse(payload['articles'][0]['release_body_verified'])
            self.assertEqual(payload['articles'][0]['published'], format_datetime(NOW-timedelta(minutes=20)))

    def test_missing_future_or_old_publication_does_not_trigger_document_reads(self):
        for clock in ('', 'October 25, 2026', format_datetime(NOW+timedelta(hours=1)), format_datetime(NOW-timedelta(hours=73))):
            payload, calls = self.retrieve({alphabet.FEED:self.rss(published=clock).encode()})
            self.assertEqual(calls, [alphabet.FEED])
            self.assertFalse(payload['articles'][0]['release_body_verified'])

    def test_a_conflicting_explicit_page_clock_is_not_overridden_by_rss(self):
        metadata = '<meta property="og:title" content="'+TITLE+'"><meta property="article:published_time" content="'+(NOW-timedelta(hours=1)).isoformat()+'">'
        payload, calls = self.retrieve({URL:self.page(metadata=metadata).encode()})
        self.assertEqual(calls, [alphabet.FEED, URL])
        self.assertTrue(payload['publication_problems'])

    def test_original_html_notice_uses_the_same_feed_and_body_checks(self):
        body = 'Alphabet will host its next financial results conference call on November 3, 2026 at 4:30 p.m. ET. The company will discuss its quarterly financial results.'
        payload, calls = self.retrieve({URL:self.page(body=body).encode()})
        self.assertEqual(calls, [alphabet.FEED, URL])
        self.assertIn('financial results conference call', payload['articles'][0]['description'])

    def test_stale_body_observation_cannot_become_fresh_in_a_new_refresh(self):
        value = self.payload(URL,self.page());value['fetched_at_epoch']=(NOW-timedelta(hours=7)).timestamp()
        payload, calls = self.retrieve({URL:value})
        self.assertEqual(calls, [alphabet.FEED,URL]);self.assertTrue(payload['publication_problems'])

    def test_changed_cached_document_text_loses_its_verified_body(self):
        payload, _ = self.retrieve(); payload['articles'][0]['description'] += '\nInvented revenue.'
        row = feeds.parse_article_items(payload,self.source,full_text=True)[0]
        self.assertEqual(row['description'],'')
        self.assertEqual(row['evidence_scope'],'headline only')

    def test_routine_call_scheduling_is_not_made_material_by_the_new_results_pattern(self):
        for title in ('Alphabet Announces Date of Third Quarter 2026 Financial Results Conference Call', 'Alphabet Announces Third Quarter 2026 Earnings Conference Call'):
            self.assertEqual(editor.materiality({'kind':'company','title':title}),'')

    def test_cached_original_results_still_receive_an_independent_review_without_new_reads(self):
        self.seed(); client=Client(leads=[],quote=QUOTE)
        result=self.run_desk(client,fetch=Mock(side_effect=AssertionError('Cached original body is sufficient')))
        self.assertEqual(result['details']['approved'],1)
        self.assertEqual(result['details']['original_reads'],0)
        self.assertEqual(len(client.calls),2)
        self.assertEqual(client.calls[0]['max_tool_calls'],2)
        approved=desk.approved(NOW)[0]
        self.assertEqual(approved['document_url'], PDF)
        self.assertEqual(approved['discovery_evidence']['document_url'],PDF)
        self.assertEqual(len(build_evidence({**approved,'materiality':'earnings'},approved['source_excerpt'],approved['excerpt_scope'])['facts']),3)

    def test_direct_web_lead_resolves_to_original_feed_and_document_within_existing_budget(self):
        client=Client(leads=[{'title':TITLE,'url':URL,'topic':'company'}],quote=QUOTE);calls=[]
        def fetch(url):calls.append(url);return self.raw(url)
        result=self.run_desk(client,fetch=fetch)
        self.assertEqual(result['details']['approved'],1)
        self.assertEqual(result['details']['original_reads'],3)
        self.assertEqual(calls,[alphabet.FEED,URL,PDF])
        self.assertEqual(len(client.calls),2)

    def test_reference_change_cannot_pass_the_independent_source_proof(self):
        self.seed();self.run_desk(Client(leads=[],quote=QUOTE))
        value=desk.approved(NOW)[0];value['document_url']='https://attacker.test/report.pdf'
        with self.assertRaises(ValueError):desk.check_proof(value,NOW)

    def test_schema_four_history_does_not_gain_new_earnings_facts(self):
        value={'title':TITLE,'url':URL,'publisher_symbol':'GOOG','published':NOW.isoformat(),'source_checked_at':NOW.isoformat(),'materiality':'earnings'}
        from pypdf import PdfReader
        from io import BytesIO
        text=PdfReader(BytesIO(earnings_pdf())).pages[0].extract_text()
        old=build_evidence(value,text,'original release excerpt',schema=4)
        new=build_evidence(value,text,'original release excerpt')
        self.assertEqual(old['schema'],4);self.assertEqual(old['facts'],[])
        self.assertEqual(new['schema'],5);self.assertEqual(len(new['facts']),3)

    def test_ambiguous_adjusted_or_forecast_values_are_not_reported_as_current_gaap_facts(self):
        base=TITLE+'\n'+QUOTE+'\nConsolidated Alphabet operating margin was 31.8%.\nNet income available to common stockholders was $2.6 billion and EPS was $2.12.\nSundar Pichai'
        from src.intelligence.alphabet_source import results_facts
        for altered in (base.replace('EPS was','Adjusted EPS was'),base.replace('EPS was','We expect EPS was'),
                        base.replace('EPS was','Management expected EPS was'),base.replace('EPS was','Prior year EPS was')):
            self.assertFalse(any(row['field']=='reported_eps' for row in results_facts(altered,TITLE)))
        self.assertEqual(results_facts(base,TITLE.replace('Third','Second')),[])

    def test_feed_or_document_cannot_have_been_observed_before_its_publication(self):
        for url, body in ((alphabet.FEED,self.rss()),(PDF,earnings_pdf())):
            value=self.payload(url,body);value['fetched_at_epoch']=(NOW-timedelta(hours=1)).timestamp()
            payload,_=self.retrieve({url:value})
            self.assertFalse(payload['articles'][0]['release_body_verified'])

    def test_feed_redirect_is_not_relabelled_as_the_native_rss(self):
        value=self.payload(alphabet.FEED,self.rss());value['final_url']=URL
        with self.assertRaises(ValueError):self.retrieve({alphabet.FEED:value})

    def test_only_one_fresh_release_can_request_a_detail_document(self):
        second='<item><title>Alphabet Announces an Investment</title><link>'+URL.replace('Fixture','Second')+'</link><pubDate>'+format_datetime(NOW-timedelta(hours=1))+'</pubDate></item>'
        body=self.rss().replace('</channel>',second+'</channel>')
        _,calls=self.retrieve({alphabet.FEED:body.encode()})
        self.assertEqual(calls,[alphabet.FEED,URL,PDF])

    def test_binary_pdf_fetch_preserves_bytes_and_does_not_write_them_to_json_cache(self):
        raw=earnings_pdf()
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,limit):return raw[:limit]
            def geturl(self):return PDF
        with patch.object(feeds,'urlopen',return_value=Response()),patch.object(feeds,'set_cached_source') as cached:
            value=feeds.fetch_url(PDF,binary=True)
        self.assertEqual(value['body'],raw)
        cached.assert_not_called()

    def test_rate_limited_feed_keeps_its_cooldown_during_forced_refresh(self):
        error = HTTPError(alphabet.FEED, 429, 'Slow down', {}, None)
        with patch.object(feeds.time, 'time', return_value=NOW.timestamp()), patch.object(feeds, 'urlopen', side_effect=error) as request:
            first = feeds.fetch_source(self.source)
            self.assertEqual(first.get('http_status'), 429)
            self.assertEqual(first['retry_after_epoch'], NOW.timestamp() + 900)
            with patch.object(feeds.time, 'time', return_value=NOW.timestamp() + 360):
                again = feeds.fetch_source(self.source, force_refresh=True)
            self.assertEqual(request.call_count, 1)
        self.assertEqual(again['fetched_at_epoch'], first['fetched_at_epoch'])
        self.assertEqual(again['retry_after_epoch'], first['retry_after_epoch'])
        self.assertTrue(again['cache_hit'])
        self.assertEqual(first['body'], '')
        self.assertEqual(feeds.describe_source(self.source, first, NOW)['status'], 'limited')

    def test_structured_feed_retains_bounded_publisher_retry_after(self):
        for supplied, seconds in (('3600', 3600), ('999999', 21600)):
            with self.subTest(supplied=supplied), patch.object(feeds, 'CACHE_FILE', self.root / ('retry-' + supplied + '.json')):
                error = HTTPError(alphabet.FEED, 429, 'Slow down', {'Retry-After': supplied}, None)
                with patch.object(feeds.time, 'time', return_value=NOW.timestamp()), patch.object(feeds, 'urlopen', side_effect=error):
                    value = feeds.fetch_source(self.source)
                self.assertEqual(value['retry_after_epoch'], NOW.timestamp() + seconds)

    def test_feed_can_recover_after_the_original_cooldown_expires(self):
        error = HTTPError(alphabet.FEED, 429, 'Slow down', {}, None)
        raw = self.rss(published=format_datetime(NOW-timedelta(hours=73))).encode()
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, limit): return raw[:limit]
            def geturl(self): return alphabet.FEED
        class Clock(type(NOW)):
            @classmethod
            def now(cls, tz=None): return cls.fromtimestamp(feeds.time.time(), tz)
        with patch.object(feeds, 'datetime', Clock), patch.object(feeds.time, 'time', return_value=NOW.timestamp()) as clock, patch.object(feeds, 'urlopen', side_effect=[error, Response()]) as request:
            feeds.fetch_source(self.source)
            clock.return_value = NOW.timestamp() + 899
            self.assertEqual(feeds.fetch_source(self.source)['status'], 'error')
            self.assertEqual(request.call_count, 1)
            clock.return_value += 1
            value = feeds.fetch_source(self.source)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(value['status'], 'ok')
        self.assertEqual(value['original_profile'], 2)
        self.assertFalse(value['articles'][0]['release_body_verified'])

    def test_other_structured_publishers_keep_their_http_backoff(self):
        sources = [next(row for row in feeds.NEWS_SOURCES if row.get('format') == kind)
                   for kind in ('index', 'treasury', 'palantir')]
        for source in sources:
            with self.subTest(source=source['name']):
                error = HTTPError(source['url'], 403, 'Forbidden', {}, None)
                with patch.object(feeds.time, 'time', return_value=NOW.timestamp()), patch.object(feeds, 'urlopen', side_effect=error) as request:
                    first = feeds.fetch_source(source)
                    second = feeds.fetch_source(source, force_refresh=True)
                self.assertEqual(first.get('http_status'), 403)
                self.assertEqual(first['retry_after_epoch'], NOW.timestamp() + 3600)
                self.assertTrue(second['cache_hit'])
                self.assertEqual(request.call_count, 1)

    def test_invalid_release_feed_still_has_a_short_parse_failure_retry(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, limit): return b'<html>not an original release feed</html>'
            def geturl(self): return alphabet.FEED
        with patch.object(feeds.time, 'time', return_value=NOW.timestamp()), patch.object(feeds, 'urlopen', return_value=Response()):
            value = feeds.fetch_source(self.source)
        self.assertEqual(value['status'], 'error')
        self.assertEqual(value['retry_after_epoch'], NOW.timestamp() + 300)
        self.assertNotIn('http_status', value)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--windows-socketpair',action='store_true');args=parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair:stack.enter_context(patch.object(socket,'socketpair',portable_tcp_socketpair))
        traffic=stack.enter_context(offline_network_guard())
        result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    passed=result.wasSuccessful() and not traffic['blocked']
    print(f"Alphabet Source Check: {'PASS' if passed else 'FAIL'} ({result.testsRun} tests)")
    return 0 if passed else 1


if __name__=='__main__':raise SystemExit(main())
