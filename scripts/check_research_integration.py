"""Offline regression checks for dated public evidence and delivered report context."""

from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DAILY_REPORT_LIVE_QUOTES", "0")

from src.intelligence import research_context as context_module
from src.intelligence import research_ingestion as ingestion
from src.intelligence import research_store as store


NOW = datetime(2026, 10, 16, 17, 0, tzinfo=timezone.utc)
SEED = PROJECT_ROOT / "resources/research/empower_q3_2026.json"


def manifest() -> dict:
    return json.loads(SEED.read_text(encoding="utf-8"))


def market_payload() -> dict:
    return {"cached_at": NOW.timestamp(), "market_moves": [
        {"symbol": "^IXIC", "move": 0.4}, {"symbol": "TLT", "move": -0.3},
        {"symbol": "MSFT", "move": 0.8},
    ]}


def minimal_pdf(text: str) -> bytes:
    # A real text PDF fixture, so extraction tests exercise the actual PdfReader API.
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = ("BT /F1 10 Tf 20 760 Td (" + escaped + ") Tj ET").encode("ascii")
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents 5 0 R >>",
               b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"]
    result = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(result)
    result += f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode()
    result += b"".join(f"{offset:010} 00000 n \n".encode() for offset in offsets[1:])
    result += f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return result


class ResearchChecks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="smart-money-research-check-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "data/public_store.json"
        self.seeds = self.root / "empty-seeds"
        self.cache = self.root / "market.json"
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"RESEARCH_STORE_FILE": str(self.path), "RESEARCH_SEED_DIR": str(self.seeds), "RESEARCH_ENABLED": "1"}).start()
        patch.object(store, "utc_now", return_value=NOW).start()
        patch.object(context_module, "utc_now", return_value=NOW).start()
        patch.object(context_module, "MARKET_CACHE", self.cache).start()

    def save(self, value=None):
        value = manifest() if value is None else value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        store.write_documents([value], self.path)

    def test_private_draft_is_not_public_research(self):
        value = manifest()
        value["visibility"] = "private_draft"
        with self.assertRaises(store.ResearchError):
            store.import_document(value)
        self.assertFalse(self.path.exists())

    def test_unreviewed_manifest_is_not_public(self):
        value = manifest()
        value["reviewed"] = False
        with self.assertRaises(store.ResearchError):
            store.validate_document(value)

    def test_private_account_kind_is_rejected(self):
        value = manifest()
        value["source"]["kind"] = "account_update"
        with self.assertRaises(store.ResearchError):
            store.validate_document(value)

    def test_contact_details_are_rejected_without_echoing_them(self):
        value = manifest()
        value["claims"][0]["text"] = "Contact owner@example.test for this account."
        with self.assertRaises(store.ResearchError) as caught:
            store.validate_document(value)
        self.assertNotIn("owner@example.test", str(caught.exception))

    def test_account_metrics_are_rejected(self):
        value = manifest()
        value["claims"][0]["text"] = "Dividends received this month are private."
        with self.assertRaises(store.ResearchError):
            store.validate_document(value)

    def test_unknown_private_fields_are_not_persisted(self):
        value = manifest()
        value["raw_text"] = "private source text"
        normalized = store.validate_document(value)
        self.assertNotIn("private source text", json.dumps(normalized))

    def test_partial_preview_cannot_supply_an_active_claim(self):
        value = manifest()
        value["source"].update(kind="article_preview", completeness="partial")
        for claim in value["claims"]:
            claim["expires_at"] = "2026-10-10T00:00:00+00:00"
        normalized = store.validate_document(value)
        claims, counts = store.eligible_claims([normalized], NOW)
        self.assertFalse(claims)
        self.assertEqual(counts["withheld"], 4)

    def test_quantitative_metrics_need_a_future_supported_import(self):
        value = manifest()
        value["claims"][0]["return_percent"] = 3.5
        with self.assertRaises(store.ResearchError):
            store.validate_document(value)

    def test_source_hash_is_required(self):
        value = manifest()
        value["source"]["sha256"] = "not-a-content-hash"
        with self.assertRaises(store.ResearchError):
            store.validate_document(value)

    def test_claim_page_must_exist(self):
        value = manifest()
        value["claims"][0]["pages"] = [21]
        with self.assertRaises(store.ResearchError):
            store.validate_document(value)

    def test_duplicate_source_issues_are_not_counted_twice(self):
        value = manifest()
        value["issues"] += deepcopy(value["issues"])
        self.assertEqual(len(store.validate_document(value)["issues"]), 1)

    def test_malformed_issue_collection_has_a_safe_validation_error(self):
        value = manifest()
        value["issues"] = None
        with self.assertRaises(store.ResearchError):
            store.validate_document(value)

    def test_dates_are_validated(self):
        value = manifest()
        value["claims"][0]["as_of"] = "not-a-date"
        with self.assertRaises(store.ResearchError):
            store.validate_document(value)

    def test_quarterly_commentary_cannot_live_forever(self):
        value = manifest()
        value["claims"][0]["expires_at"] = "2027-09-30"
        with self.assertRaises(store.ResearchError):
            store.validate_document(value)

    def test_forecasts_have_a_short_review_window(self):
        value = manifest()
        value["claims"][0]["type"] = "forecast"
        with self.assertRaises(store.ResearchError):
            store.validate_document(value)

    def test_future_known_at_is_not_available(self):
        value = manifest()
        claims, counts = store.eligible_claims([value], NOW - timedelta(days=1))
        self.assertEqual(claims, [])
        self.assertEqual(counts["future"], 4)

    def test_publication_date_cannot_be_bypassed_by_known_at(self):
        value = manifest()
        value["source"]["published_at"] = (NOW + timedelta(days=1)).isoformat()
        claims, counts = store.eligible_claims([value], NOW)
        self.assertFalse(claims)
        self.assertEqual(counts["future"], 4)

    def test_future_as_of_is_withheld(self):
        value = manifest()
        for claim in value["claims"]:
            claim["as_of"] = (NOW + timedelta(days=1)).isoformat()
        self.assertFalse(store.eligible_claims([value], NOW)[0])

    def test_expired_claims_are_archived(self):
        claims, counts = store.eligible_claims([manifest()], NOW + timedelta(days=90))
        self.assertFalse(claims)
        self.assertEqual(counts["expired"], 4)

    def test_symbol_scope_does_not_leak_an_ai_claim_to_every_stock(self):
        claims, _ = store.eligible_claims([manifest()], NOW, "AVAV")
        self.assertTrue(claims)
        self.assertFalse(any(c["event_id"] == "ai-capex-financing" for c in claims))
        direct, _ = store.eligible_claims([manifest()], NOW, "MSFT")
        self.assertEqual(direct[0]["event_id"], "ai-capex-financing")

    def test_repeated_event_across_publishers_counts_once(self):
        first = manifest()
        second = deepcopy(first)
        second["source"].update(sha256="a" * 64, label="Second publisher")
        self.assertEqual(len(store.eligible_claims([first, second], NOW)[0]), 4)

    def test_reimport_is_idempotent_and_preserves_known_at(self):
        self.assertTrue(store.import_document(manifest())["changed"])
        before = self.path.read_bytes()
        with patch.object(store, "utc_now", return_value=NOW + timedelta(days=1)):
            self.assertFalse(store.import_document(manifest())["changed"])
        self.assertEqual(before, self.path.read_bytes())

    def test_new_runtime_import_cannot_backdate_its_history(self):
        store.import_document(manifest())
        document = store.read_documents()[0]
        self.assertTrue(all(store.parse_time(c["known_at"]) >= NOW for c in document["claims"]))

    def test_read_only_fallback_does_not_create_runtime_files(self):
        documents = store.read_documents(path=self.path, seeds=SEED.parent)
        self.assertEqual(len(documents), 1)
        self.assertFalse(self.path.parent.exists())

    def test_corrupt_store_fails_closed_without_exposing_content(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{private broken content", encoding="utf-8")
        context = context_module.build_research_context(now=NOW)
        self.assertEqual(context["status"], "unavailable")
        self.assertFalse(context["claims"])
        self.assertIn("private broken", self.path.read_text())
        self.assertNotIn("private broken", context_module.build_research_report())

    def test_atomic_failure_preserves_last_good_store(self):
        self.save()
        before = self.path.read_bytes()
        with patch.object(store.os, "replace", side_effect=OSError("simulated write failure")):
            with self.assertRaises(OSError):
                store.write_documents([manifest()], self.path)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(list(self.path.parent.glob(".research-*.tmp")))

    def test_concurrent_import_is_rejected_without_overwriting(self):
        with store.store_lock(self.path):
            with self.assertRaises(store.ResearchError):
                store.import_document(manifest())
        self.assertFalse(self.path.with_suffix(".lock").exists())

    def test_page_18_conflicting_period_is_detected(self):
        text = "Q3 asset-class returns\nPerformance from April 1-June 30, 2026\nReturn ranges in Q2 2026."
        self.assertEqual(ingestion.find_period_conflicts([text], "Q3 2026"), [{"code": "period_conflict", "pages": [1]}])

    def test_historical_mentions_are_not_automatically_period_conflicts(self):
        self.assertEqual(ingestion.find_period_conflicts(["Q3 2026 outlook. Compare with Q2 2026 history."], "Q3 2026"), [])

    def test_conflict_quarantines_affected_claim_only(self):
        value = manifest()
        value["claims"][0]["pages"] = [18]
        claims, counts = store.eligible_claims([value], NOW)
        self.assertEqual(len(claims), 3)
        self.assertEqual(counts["withheld"], 1)

    def test_missing_market_data_is_unavailable(self):
        self.assertIn("unavailable", context_module.market_check({}, NOW))

    def test_fresh_cache_with_missing_observations_is_unavailable(self):
        self.assertIn("unavailable", context_module.market_check({"cached_at": NOW.timestamp()}, NOW))

    def test_expired_market_cache_is_labeled_stale(self):
        payload = market_payload()
        payload["cached_at"] -= 7 * 60 * 60
        self.assertIn("stale", context_module.market_check(payload, NOW))

    def test_future_market_cache_is_not_fresh(self):
        payload = market_payload()
        payload["cached_at"] += 3600
        self.assertIn("future", context_module.market_check(payload, NOW))

    def test_nonfinite_market_values_cannot_become_observations(self):
        payload = {"cached_at": NOW.timestamp(), "market_moves": [{"symbol": "TLT", "move": float("nan")}]}
        self.assertIn("unavailable", context_module.market_check(payload, NOW))

    def test_real_zero_move_is_valid_and_tlt_is_not_a_yield(self):
        payload = {"cached_at": NOW.timestamp(), "market_moves": [{"symbol": "TLT", "move": 0.0}]}
        line = context_module.market_check(payload, NOW)
        self.assertIn("+0.00% (bond-price proxy)", line)
        self.assertIn("Yields unverified", line)

    def test_company_context_has_type_date_and_source_page(self):
        context = context_module.build_research_context("MSFT", market_payload(), NOW, [manifest()])
        text = context_module.build_market_backdrop("MSFT", context)
        self.assertIn("Opinion (2026-09-30)", text)
        self.assertIn("[Empower Q3 2026, p9]", text)
        self.assertIn("MSFT +0.80%", text)

    def test_feature_switch_disables_context_without_reading_documents(self):
        with patch.dict(os.environ, {"RESEARCH_ENABLED": "0"}), patch.object(context_module, "read_documents", side_effect=AssertionError("should not read")):
            self.assertEqual(context_module.build_market_backdrop("MSFT"), "")

    def test_active_label_requires_delivered_evidence(self):
        self.assertTrue(context_module.validate_research_output("Document Research: active."))

    def test_unsourced_research_output_is_rejected(self):
        text = "Document Research: active.\n• Research a rumor\n• Market check: unavailable"
        self.assertTrue(context_module.validate_research_output(text))

    def test_near_limit_report_is_preserved_without_false_active_label(self):
        context = context_module.build_research_context("MSFT", {}, NOW, [manifest()])
        report = "Intelligence Used Today\nExisting sources\n\nTheme Read\n• Existing theme\n\nMarket Snapshot\nUnknown"
        self.assertEqual(context_module.attach_daily_research(report, context, len(report)), report)

    def test_forecast_label_survives_rendering(self):
        value = manifest()
        value["claims"] = [value["claims"][0]]
        value["claims"][0].update(type="forecast", as_of="2026-10-15", expires_at="2026-10-25")
        context = context_module.build_research_context("MSFT", {}, NOW, [value])
        self.assertIn("Forecast (2026-10-15)", context_module.build_market_backdrop("MSFT", context))


@unittest.skipUnless(importlib.util.find_spec("pypdf"), "Install requirements.txt to exercise PDF extraction.")
class PDFChecks(ResearchChecks):
    # Only PDF-specific methods are loaded below; this class reuses the isolated filesystem setup.
    def test_pdf_extracts_actual_text_and_creates_private_draft(self):
        source = self.root / "report.pdf"
        source.write_bytes(minimal_pdf("Q3 2026 market research"))
        destination = self.root / "draft.json"
        result = ingestion.create_draft(source, destination, "Q3 2026")
        draft = json.loads(destination.read_text())
        self.assertEqual(result["pages"], 1)
        self.assertEqual(draft["visibility"], "private_draft")
        self.assertFalse(draft["reviewed"])
        self.assertIn("market research", draft["extracted_pages"][0]["text"])
        self.assertFalse(self.path.exists())

    def test_pdf_account_document_is_rejected_before_storage(self):
        source = self.root / "account.pdf"
        source.write_bytes(minimal_pdf("Dividends received and trades made in your account"))
        with self.assertRaises(store.ResearchError):
            ingestion.create_draft(source, self.root / "draft.json")
        self.assertFalse((self.root / "draft.json").exists())

    def test_pdf_content_hash_must_match_its_manifest(self):
        source = self.root / "report.pdf"
        source.write_bytes(minimal_pdf("Q3 market report"))
        manifest_path = self.root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest()))
        with self.assertRaises(store.ResearchError):
            ingestion.import_manifest(manifest_path, source)
        self.assertFalse(self.path.exists())

    def test_pdf_preview_is_withheld_even_if_manifest_claimed_full(self):
        source = self.root / "preview.pdf"
        source.write_bytes(minimal_pdf("Article preview. News for you. More like this."))
        value = manifest()
        value["source"].update(sha256=hashlib.sha256(source.read_bytes()).hexdigest(), page_count=1)
        value["issues"] = []
        for claim in value["claims"]:
            claim["pages"] = [1]
        manifest_path = self.root / "manifest.json"
        manifest_path.write_text(json.dumps(value))
        ingestion.import_manifest(manifest_path, source)
        self.assertFalse(store.eligible_claims(store.read_documents(), NOW)[0])


class ReportChecks(ResearchChecks):
    def setUp(self):
        super().setUp()
        self.save()
        self.cache.write_text(json.dumps(market_payload()))
        from src.reports import daily_report, scorecard, tradeplan_report
        from scripts import check_report_consistency
        self.daily = daily_report
        self.scorecard = scorecard
        self.tradeplan = tradeplan_report
        self.legacy = check_report_consistency
        self.stock = deepcopy(check_report_consistency.STOCKS[0])
        patch.object(scorecard, "build_headline_impact_summary", return_value="Offline headlines.").start()

    def daily_fixture(self):
        return self.legacy.BuilderConsistencyChecks.build_daily_fixture(SimpleNamespace(daily=self.daily), NOW)

    def test_final_daily_report_preserves_sourced_context_after_rewrites(self):
        report = self.daily_fixture()
        result = self.legacy.validate_daily_report_quality(report)
        self.assertTrue(result["passes"], result)
        self.assertIn("Document Research: active.", report)
        self.assertIn("• Research Opinion (2026-09-30)", report)
        self.assertIn("[Empower Q3 2026, p9]", report)
        self.assertEqual(context_module.validate_research_output(report), [])

    def test_report_tradeplan_and_active_scorecard_share_claim_and_risks(self):
        from src.scoring import scoring_engine
        with patch.object(scoring_engine, "get_stock_scores", return_value=[self.stock]):
            tradeplan = self.tradeplan.build_tradeplan_report("MSFT")
        scorecard = self.scorecard.build_scorecard(self.stock)
        report = self.daily_fixture()
        for text in [tradeplan, scorecard, report]:
            self.assertIn(manifest()["claims"][0]["text"], text)
            self.assertIn("Score Risk: Controlled", text)
            self.assertIn("Setup Risk: Medium-High", text)

    def test_research_does_not_modify_numeric_scores_or_ranking(self):
        from src.intelligence.opportunity_ranker import rank_daily_opportunities
        stocks = deepcopy(self.legacy.STOCKS)
        with patch.dict(os.environ, {"RESEARCH_ENABLED": "0"}):
            first = rank_daily_opportunities(stocks, [], {}, record_memory=False)
        with patch.dict(os.environ, {"RESEARCH_ENABLED": "1"}):
            second = rank_daily_opportunities(stocks, [], {}, record_memory=False)
        self.assertEqual(first, second)
        self.assertEqual(stocks, self.legacy.STOCKS)

    def test_new_provider_does_not_cast_historical_opinions_as_live_risk_votes(self):
        block = context_module.research_context_provider()
        self.assertEqual(block.feature, "Document Research")
        self.assertEqual(block.themes, [])
        self.assertEqual(block.risks, [])
        self.assertIn("p9", block.signal)

    def test_missing_cache_is_not_reported_as_no_macro_pressure(self):
        context = dict.fromkeys(["nasdaq", "sp500", "russell", "vix", "oil", "gold", "tlt"], 0)
        context["_market_payload"] = {}
        self.assertIn("unavailable", self.daily.get_macro_pressure(context))
        self.assertNotEqual("no major macro pressure", self.daily.get_macro_pressure(context))

    def test_summary_does_not_display_missing_assets_as_zero_moves(self):
        context = dict.fromkeys(["nasdaq", "sp500", "russell", "vix", "oil", "gold", "tlt"], 0)
        payload = market_payload()
        payload["market_moves"][0]["move"] = 0.0
        context["_market_payload"] = payload
        line = self.daily.build_market_moves_line(context, [])
        self.assertIn("Nasdaq +0.00%", line)
        self.assertIn("VIX unavailable", line)
        self.assertNotIn("VIX +0.00%", line)
        self.assertIn("incomplete", self.daily.get_macro_pressure(context))

    def test_quality_card_exposes_research_context_check(self):
        from src.commands import reportcheck_commands
        with patch.object(reportcheck_commands, "build_daily_report", return_value=self.daily_fixture()):
            output = reportcheck_commands.build_daily_report_quality_card()
        self.assertIn("Research Context: PASS", output)

    def test_registered_research_command_delivers_dated_context(self):
        with patch("openai.OpenAI"):
            from src.commands import register_commands
        app = Mock()
        register_commands.register_commands(app)
        handlers = [call.args[0] for call in app.add_handler.call_args_list]
        handler = next(item for item in handlers if "research" in item.commands)
        update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
        asyncio.run(handler.callback(update, SimpleNamespace(args=["MSFT"])))
        text = "\n".join(call.kwargs.get("text", "") for call in update.message.reply_text.await_args_list)
        self.assertIn("Status: ACTIVE", text)
        self.assertIn("Opinion (2026-09-30)", text)
        self.assertIn("[Empower Q3 2026, p9]", text)
        self.assertIn("bond-price proxy", text)

    def test_registered_scorecard_command_uses_the_updated_active_builder(self):
        with patch("openai.OpenAI"):
            from src.commands import register_commands, market_commands
        app = Mock()
        register_commands.register_commands(app)
        handler = next(call.args[0] for call in app.add_handler.call_args_list if "scorecard" in call.args[0].commands)
        update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
        with patch.object(market_commands, "get_stock_scores", return_value=[self.stock]), patch.object(market_commands, "fetch_quotes_for_symbols", return_value={}):
            asyncio.run(handler.callback(update, SimpleNamespace(args=["MSFT"])))
        text = "\n".join(str(call.args[0]) if call.args else str(call.kwargs.get("text", "")) for call in update.message.reply_text.await_args_list)
        self.assertIn("Market Backdrop", text)
        self.assertIn("[Empower Q3 2026, p9]", text)
        self.assertIn("Score Risk: Controlled", text)

    def test_source_refresh_has_cache_only_research_step(self):
        from src.jobs.source_refresh_job import refresh_document_research
        output = refresh_document_research()
        self.assertIn("active", output)
        self.assertIn("4 eligible event(s)", output)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", action="store_true", help="Run storage/rendering/PDF checks without bot dependencies.")
    args = parser.parse_args(argv)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite(loader.loadTestsFromTestCase(ResearchChecks))
    # Do not rerun inherited base checks in the specialized fixture classes.
    for cls, prefix in [(PDFChecks, "test_pdf_"), (ReportChecks, "test_")]:
        if args.core and cls is ReportChecks:
            continue
        names = [name for name in cls.__dict__ if name.startswith(prefix)]
        suite.addTests(cls(name) for name in sorted(names))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    print(f"Research Integration Check: {'PASS' if result.wasSuccessful() else 'FAIL'} ({result.testsRun} tests; {len(result.skipped)} skipped)")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
