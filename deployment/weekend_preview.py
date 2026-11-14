#!/usr/bin/env python3
"""Verify a Weekend Outlook export and write a still preview and timing handoff.

Run as smartmoney with the bot virtual environment's Python. The existing
native checker reads the live weekend state. The renderer and its patched
contract are prepared in a private directory beside the selected export.
Use --latest to export and review the latest saved bot edition in one run.
"""

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


BOT = Path("/opt/smart-money-comercio")
VIDEO = Path("/opt/smart-money-youtube")
EXPORT = "20261109T031632Z"
EDITION = "761da7dc98f8e7e7666d"
EPISODE_SHA256 = "2819e81aa9729289542ac4a5784643945320ebf4c7ddc1faa2435c7cffadd58b"
VOICEOVER_SHA256 = "655861b9e5f073d2222607359a966c1660a076fa6f83220471f9b086f0536d4f"
RENDERER_SHA256 = "61c7b2feb4ce1faa46f86a7132ae777e128b45e4c1070d63c148db6d878a02f1"
SIBLING_SHA256 = "948c06289700c9c3b165e807415d446be08ef72003000bdbf9322fefb17e3985"
ORIGINAL_CONTRACT_SHA256 = "0d207abf97eb513f8a9503f9ea396784ad0411981d471754ac2f0887e3001c50"
PATCHED_CONTRACT_SHA256 = "67071fb3dad4cc237211714fc7c74bff4442eca8807314e8a963cbfc7a6db749"
CURRENT_CONTRACT_SHA256 = "75035be528028d5d06530d7053bcac2e3c0cec6af6a0c4bb7012e571db8c1b74"
LEGACY_RUNNER_SHA256 = "effc8cd91b08419181102b99775073a4381a44c51148913ccd73f7e72f9b0342"
CONTRACT_PATH = Path("src/reports/weekend_media_contract.py")

# The previously tested Git patch, applied only inside the private preview workspace.
REVIEWED_PATCH = r"""diff --git a/src/reports/weekend_media_contract.py b/src/reports/weekend_media_contract.py
index 852c0f6..d9c3d1c 100644
--- a/src/reports/weekend_media_contract.py
+++ b/src/reports/weekend_media_contract.py
@@ -15,6 +15,12 @@ NY=ZoneInfo("America/New_York")
 # The saved branded v2 renderer was inspected without invoking speech or FFmpeg.
 REFERENCE_RENDERER_SHA256="2c275c853a087760fe9b916e2ad388bacc16568adc81893ab5863f8c63b000dc"
 WEEKEND_RENDERER_SHA256="63d2c82f3b59b3ee96d00bf196391f6fe6b28736148fb11aa481f0f44cb748e6"
+REFINED_RENDERER_SHA256="61c7b2feb4ce1faa46f86a7132ae777e128b45e4c1070d63c148db6d878a02f1"
+REFINED_WEEKEND_RENDERER_SHA256="948c06289700c9c3b165e807415d446be08ef72003000bdbf9322fefb17e3985"
+REVIEWED_RENDERERS={
+    REFERENCE_RENDERER_SHA256: WEEKEND_RENDERER_SHA256,
+    REFINED_RENDERER_SHA256: REFINED_WEEKEND_RENDERER_SHA256,
+}
@@EMPTY_CONTEXT@@
@@EMPTY_CONTEXT@@
 def digest(text):
@@ -95,8 +101,8 @@ def inspect_renderer(path):
     tree = ast.parse(source)
     constants={node.value for node in ast.walk(tree) if isinstance(node,ast.Constant) and isinstance(node.value,str)}
     fingerprint=digest(source)
-    known=fingerprint in {REFERENCE_RENDERER_SHA256,WEEKEND_RENDERER_SHA256}
-    adapted=fingerprint==WEEKEND_RENDERER_SHA256
+    adapted=fingerprint in REVIEWED_RENDERERS.values()
+    known=adapted or fingerprint in REVIEWED_RENDERERS
     return {"status":"PREVIEW_COMPATIBLE" if adapted else "WEEKEND_BANNER_ADAPTER_REQUIRED" if known else "CUSTOM_RENDERER_REVIEW_REQUIRED",
         "renderer_sha256":sha256(raw).hexdigest(),"known_saved_v2":known,"weekend_adapter":adapted,
         "scene_structure":"2–14 dynamic scenes accepted by the saved v2 renderer" if known else "unverified renderer revision",
@@ -107,23 +113,57 @@ def inspect_renderer(path):
@@EMPTY_CONTEXT@@
@@EMPTY_CONTEXT@@
 def adapted_renderer(source):
-    if digest(source)!=REFERENCE_RENDERER_SHA256:raise ValueError("Renderer differs from the reviewed v2 source; inspect the deployed customization before adapting it")
+    fingerprint = digest(source)
+    if fingerprint not in REVIEWED_RENDERERS:
+        raise ValueError("Renderer differs from the reviewed v2 source; inspect the deployed customization before adapting it")
     replacements=(
         ('def compose_slide(heading, bullets, output, index, demo=False):',
          'def compose_slide(heading, bullets, output, index, demo=False, edition_label="DAILY MARKET BRIEF"):'),
         ('d.text((1480, 98), "DAILY MARKET BRIEF", font=font(27, True), fill=WHITE)',
-         'd.text((1480, 98), edition_label, font=font(27, True), fill=WHITE)'),
-        ('compose_slide(seg["heading"], seg.get("bullets") or [], still, i, demo)',
-         'compose_slide(seg["heading"], seg.get("bullets") or [], still, i, demo, edition_label="WEEKEND OUTLOOK" if data.get("edition_type") == "weekend_outlook" else "DAILY MARKET BRIEF")'),
-        ('final = folder / "Smart_Money_Project_Daily_Brief.mp4"',
-         'final = folder / ("Smart_Money_Project_Weekend_Outlook.mp4" if data.get("edition_type") == "weekend_outlook" else "Smart_Money_Project_Daily_Brief.mp4")'),
-        ('"tags": ["Smart Money Project", "daily market brief", "investing", "market intelligence"],',
-         '"tags": ["Smart Money Project", "weekend outlook" if data.get("edition_type") == "weekend_outlook" else "daily market brief", "investing", "market intelligence"],'),
-        ('"source_edition_date": data.get("date"),',
-         '"source_edition_date": data.get("date"),\n        "source_edition_type": data.get("edition_type", "daily_brief"),\n        "bot_edition_id": data.get("bot_edition_id"),\n        "voiceover_sha256": data.get("voiceover_sha256"),\n        "weekend_narration_revision": data.get("weekend_narration_revision"),'),
-        ('illustrated, branded daily scenes.', 'illustrated, branded research scenes.'))
+         'd.text((1480, 98), edition_label, font=font(27, True), fill=WHITE)'))
+    if fingerprint == REFINED_RENDERER_SHA256:
+        replacements += (
+            ('    mode = data.get("mode")\n',
+             '''    mode = data.get("mode")
+    if not getattr(args, "preview_only", False):
+        raise ValueError("Weekend production is on hold; use --preview-only")
+    revision = data.get("weekend_narration_revision")
+    schema = data.get("voiceover_schema")
+    if (data.get("edition_type") != "weekend_outlook" or mode != "draft_review_required"
+            or data.get("review_required") is not True or data.get("contains_synthetic_media") is not True
+            or type(revision) is not int or revision != 2 or type(schema) is not int or schema != 2):
+        raise ValueError("Use a native review-required Weekend Outlook revision-2 export")
+'''),
+            ('            compose_slide(seg["heading"], seg.get("bullets") or [], folder / f"preview_{i:02}.jpg", i, demo)',
+             '''            compose_slide(seg["heading"], seg.get("bullets") or [], folder / f"preview_{i:02}.jpg", i,
+                          demo, edition_label="WEEKEND OUTLOOK")'''),
+            ('''        (folder / "preview.json").write_text(json.dumps({"mode":"visual_preview_only","audio_generated":False,
+            "uploaded":False,"bot_edition_id":data.get("bot_edition_id"),"scene_count":len(parts)},indent=2),encoding="utf-8")''',
+             '''        preview = {
+            "mode": "visual_preview_only", "edition_type": data["edition_type"],
+            "bot_edition_id": data["bot_edition_id"], "weekend_narration_revision": revision,
+            "voiceover_sha256": data["voiceover_sha256"], "scene_count": len(parts),
+            "audio_generated": False, "uploaded": False, "review_required": True,
+            "paid_production_ready": False,
+        }
+        (folder / "preview.json").write_text(json.dumps(preview, indent=2), encoding="utf-8")'''),
+        )
+    else:
+        replacements += (
+            ('compose_slide(seg["heading"], seg.get("bullets") or [], still, i, demo)',
+             'compose_slide(seg["heading"], seg.get("bullets") or [], still, i, demo, edition_label="WEEKEND OUTLOOK" if data.get("edition_type") == "weekend_outlook" else "DAILY MARKET BRIEF")'),
+            ('final = folder / "Smart_Money_Project_Daily_Brief.mp4"',
+             'final = folder / ("Smart_Money_Project_Weekend_Outlook.mp4" if data.get("edition_type") == "weekend_outlook" else "Smart_Money_Project_Daily_Brief.mp4")'),
+            ('"tags": ["Smart Money Project", "daily market brief", "investing", "market intelligence"],',
+             '"tags": ["Smart Money Project", "weekend outlook" if data.get("edition_type") == "weekend_outlook" else "daily market brief", "investing", "market intelligence"],'),
+            ('"source_edition_date": data.get("date"),',
+             '"source_edition_date": data.get("date"),\n        "source_edition_type": data.get("edition_type", "daily_brief"),\n        "bot_edition_id": data.get("bot_edition_id"),\n        "voiceover_sha256": data.get("voiceover_sha256"),\n        "weekend_narration_revision": data.get("weekend_narration_revision"),'),
+            ('illustrated, branded daily scenes.', 'illustrated, branded research scenes.'),
+        )
     for before,after in replacements:
         if source.count(before)!=1:raise ValueError("Reviewed renderer anchor changed")
         source=source.replace(before,after,1)
+    if digest(source) != REVIEWED_RENDERERS[fingerprint]:
+        raise ValueError("Weekend renderer output differs from the reviewed source")
     compile(source,"weekend_render_episode.py","exec")
     return source
""".replace("@@EMPTY_CONTEXT@@", " ")


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical_source(raw):
    return raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def load_preview_contract(stage):
    original = canonical_source((BOT / CONTRACT_PATH).read_bytes())
    fingerprint = sha256(original)
    staged = stage / CONTRACT_PATH
    staged.parent.mkdir(parents=True)
    staged.write_bytes(original)

    if fingerprint == ORIGINAL_CONTRACT_SHA256:
        print("Ubuntu contract: rules-30 baseline. Applying reviewed patch in the preview workspace.", flush=True)
        git_env = {**os.environ, "GIT_DIR": str(stage / ".git"), "GIT_WORK_TREE": str(stage)}
        subprocess.run(["git", "init", "--quiet", "--template="], cwd=stage, env=git_env, check=True)
        subprocess.run(
            ["git", "-c", "core.autocrlf=false", "apply", "-"],
            cwd=stage, env=git_env, input=REVIEWED_PATCH.encode("utf-8"), check=True,
        )
        fingerprint = PATCHED_CONTRACT_SHA256
    elif fingerprint == PATCHED_CONTRACT_SHA256:
        print("Ubuntu contract: refined-v2 patch already present.", flush=True)
    elif fingerprint == CURRENT_CONTRACT_SHA256:
        print("Ubuntu contract: Weekend Outlook rules 32.", flush=True)
    else:
        raise ValueError(f"The deployed weekend contract has an unreviewed fingerprint {fingerprint}")
    if sha256(staged.read_bytes()) != fingerprint:
        raise ValueError("The staged weekend contract differs from the reviewed source")

    package = importlib.import_module("src.reports")
    name = "src.reports.weekend_media_contract"
    spec = importlib.util.spec_from_file_location(name, staged)
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    sys.modules[name] = contract
    package.weekend_media_contract = contract


def write_narration_review(result, packet, report):
    rate = packet["voiceover_quality"]["words_per_minute"]
    scenes = []
    words = 0
    for index, segment in enumerate(packet["segments"]):
        narration = segment["narration"]
        count = len(re.findall(r"\b[\w]+(?:['-][\w]+)*\b", narration))
        start = round(words * 60 / rate, 1)
        words += count
        still = Path("stills") / f"preview_{index:02}.jpg"
        scenes.append({
            "scene": index + 1,
            "heading": segment["heading"],
            "still": still.as_posix(),
            "still_sha256": sha256((result / still).read_bytes()),
            "narration": narration,
            "source_ids": segment["source_ids"],
            "words": count,
            "estimated_start_seconds": start,
            "estimated_end_seconds": round(words * 60 / rate, 1),
        })
    if words != report["words"] or scenes[-1]["estimated_end_seconds"] != report["estimated_seconds"]:
        raise ValueError("Scene timing does not match the verified narration metrics")
    review = {
        "schema": 1,
        "mode": "narration_timing_review",
        "edition_type": packet["edition_type"],
        "title": packet["title"],
        "bot_edition_id": report["edition_id"],
        "episode_sha256": report["episode_sha256"],
        "voiceover_sha256": report["voiceover_sha256"],
        "weekend_narration_revision": report["narration_revision"],
        "words": words,
        "words_per_minute": rate,
        "estimated_seconds": report["estimated_seconds"],
        "timing_basis": "estimated_from_spoken_word_count",
        "preflight": "preflight.json",
        "still_review": "stills/preview.json",
        "review_required": True,
        "paid_production_ready": False,
        "scenes": scenes,
    }
    (result / "narration_review.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )


def install_runner(target):
    if target.is_symlink():
        raise ValueError("The installed weekend preview runner is a symbolic link")
    if not target.is_file():
        return
    installed = target.read_bytes()
    current = canonical_source(Path(__file__).read_bytes())
    fingerprint = sha256(canonical_source(installed))
    if fingerprint == sha256(current):
        return
    if fingerprint != LEGACY_RUNNER_SHA256:
        raise ValueError("The installed weekend preview runner has local changes. Review it before updating the preview.")
    with tempfile.NamedTemporaryFile(prefix=".weekend_preview.", dir=target.parent, delete=False) as output:
        staged = Path(output.name)
        try:
            output.write(current)
            output.flush()
            os.fsync(output.fileno())
        except (OSError, ValueError):
            output.close()
            staged.unlink(missing_ok=True)
            raise
    try:
        owner = target.stat()
        os.chown(staged, owner.st_uid, owner.st_gid)
        staged.chmod(owner.st_mode & 0o777)
        if target.is_symlink() or target.read_bytes() != installed:
            raise ValueError("The installed weekend preview runner changed during the update")
        os.replace(staged, target)
    finally:
        staged.unlink(missing_ok=True)
    print("Weekend Outlook preview runner updated.", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--install-runner", action="store_true", help=argparse.SUPPRESS)
    selection.add_argument("--latest", action="store_true", help="Export and review the latest saved Weekend Outlook")
    selection.add_argument("--export-dir", type=Path, help="Directory with the fresh weekend JSON/TXT pair")
    parser.add_argument("--edition", help="Expected 20-character bot edition ID")
    args = parser.parse_args(argv)
    if args.install_runner:
        if args.edition is not None:
            parser.error("--install-runner does not take an edition")
        install_runner(VIDEO / "bin/weekend_preview.py")
        return 0
    pinned = not args.latest and args.export_dir is None
    if args.edition is not None and not re.fullmatch(r"[0-9a-f]{20}", args.edition):
        parser.error("--edition must be a 20-character lowercase hexadecimal ID")
    if pinned and args.edition not in (None, EDITION):
        parser.error("Use --export-dir to review a different edition")
    expected_edition = EDITION if pinned else args.edition
    export_root = (VIDEO / "output/weekend_exports").resolve(strict=True)
    if not args.latest:
        pair = (export_root / EXPORT if pinned else args.export_dir).resolve(strict=True)
        if not pair.is_dir() or pair == export_root or not pair.is_relative_to(export_root):
            raise ValueError(f"Choose an export directory inside {export_root}")

    release = VIDEO / "releases/v2"
    original_renderer = (release / "render_episode.py").read_bytes()
    fingerprint = sha256(canonical_source(original_renderer))
    print(f"Renderer SHA-256: {sha256(original_renderer)}", flush=True)
    if fingerprint != RENDERER_SHA256:
        raise ValueError(f"The deployed renderer has an unreviewed source fingerprint {fingerprint}")

    os.chdir(BOT)
    sys.path.insert(0, str(BOT))
    if args.latest:
        from scripts import export_weekend_outlook

        pair = Path(tempfile.mkdtemp(prefix="review_export.", dir=export_root))
        if export_weekend_outlook.main(["--output", str(pair / "weekend_outlook.json")]):
            pair.rmdir()
            return 1
    with tempfile.TemporaryDirectory(prefix=".weekend_preview.", dir=pair) as temp:
        stage = Path(temp)
        load_preview_contract(stage)
        from scripts import check_weekend_media, prepare_weekend_renderer
        from src.reports.weekend_media_contract import MAX_BYTES

        episode = stage / "weekend_outlook.json"
        transcript = stage / "weekend_outlook.txt"
        for path in (episode, transcript):
            original = pair / path.name
            if not original.is_file() or original.stat().st_size > MAX_BYTES:
                raise ValueError(f"Expected a bounded native export file at {original}")
            shutil.copyfile(original, path)

        staged_release = stage / "release"
        staged_release.mkdir()
        source = staged_release / "render_episode.py"
        source.write_bytes(original_renderer)
        if prepare_weekend_renderer.main(["--renderer", str(source)]):
            return 1
        sibling = staged_release / "weekend_render_episode.py"
        if sha256(sibling.read_bytes()) != SIBLING_SHA256:
            raise ValueError("The prepared sibling differs from the reviewed still-only renderer")

        result = stage / "review"
        result.mkdir(mode=0o700)
        report_path = result / "preflight.json"
        if check_weekend_media.main([
            "--episode", str(episode), "--script", str(transcript),
            "--renderer", str(sibling), "--output", str(report_path),
        ]):
            return 1
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if (report.get("native_record") != "PASS"
                or report.get("validation_scope") != "native_edition_and_pairing"
                or report.get("narration_revision") != 2
                or report.get("all_spoken_text_in_scenes") is not True
                or report.get("paid_production_ready") is not False
                or report.get("renderer", {}).get("status") != "PREVIEW_COMPATIBLE"):
            raise ValueError("Native preflight did not confirm the export and reviewed preview renderer")
        if expected_edition and report.get("edition_id") != expected_edition:
            raise ValueError(f"Expected edition {expected_edition}; export contains {report.get('edition_id')}")
        if pinned and (report.get("episode_sha256") != EPISODE_SHA256
                       or report.get("voiceover_sha256") != VOICEOVER_SHA256
                       or report.get("segments") != 7):
            raise ValueError("Native preflight did not confirm the original pinned export")
        packet = json.loads(episode.read_text(encoding="utf-8-sig"))

        for name in ("assets", "video_refinements.py"):
            (staged_release / name).symlink_to((release / name).resolve(strict=True))
        stills = result / "stills"
        subprocess.run([
            str(VIDEO / ".venv/bin/python"), "-B", str(sibling),
            "--episode", str(episode), "--out", str(stills), "--preview-only",
        ], cwd=staged_release, env={**os.environ, "ELEVENLABS_API_KEY": "", "PYTHON_DOTENV_DISABLED": "1"}, check=True)
        audit = json.loads((stills / "preview.json").read_text(encoding="utf-8"))
        images = {path.name for path in stills.glob("preview_*.jpg")}
        if (audit.get("mode") != "visual_preview_only" or audit.get("edition_type") != "weekend_outlook"
                or audit.get("bot_edition_id") != report["edition_id"]
                or audit.get("voiceover_sha256") != report["voiceover_sha256"]
                or audit.get("weekend_narration_revision") != report["narration_revision"]
                or audit.get("scene_count") != report["segments"]
                or audit.get("audio_generated") is not False or audit.get("uploaded") is not False
                or audit.get("review_required") is not True
                or audit.get("paid_production_ready") is not False
                or images != {f"preview_{index:02}.jpg" for index in range(report["segments"])}):
            raise ValueError("Still preview did not match the verified weekend edition")
        write_narration_review(result, packet, report)

        output = pair / stage.name.replace(".weekend_preview.", "visual_review.", 1)
        if output.exists():
            raise FileExistsError(f"Preview destination already exists: {output}")
        result.rename(output)
        print(json.dumps(audit, indent=2))
        print(f"WEEKEND STILL PREVIEW PASS: {output}")
        print(f"NARRATION REVIEW: {output / 'narration_review.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, ImportError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"HOLD: {error}")
