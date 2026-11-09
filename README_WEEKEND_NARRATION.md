# Weekend narration revision 2

New Weekend Outlook builds record `narration_revision: 2` in their inputs and voiceover profile; JSON exports include `weekend_narration_revision: 2`. Existing revision-1 records keep their original report, script, identity and exact export. A frozen revision-1 fixture verifies their hashes. The daily narrator is unchanged.

New reports use “The disclosure” for weekday publications and keep weekend updates labeled separately. New speech expands DOL to the U.S. Department of Labor, reads Mk21A as “Mark twenty-one A,” omits the redundant DEAMS initialism after its full name, and spells isolated DEAMS as letters. The Air Force uses both Mk21A and Mark 21A for the designation in its [acquisition report, page 28](https://www.af.mil/Portals/1/documents/1/annual_report_web.pdf). That naming reference does not supply current program or financial facts.

The written calendar retains all five days. Speech lists verified events and gives one incomplete-coverage statement. A day without evidence is not described as having no scheduled events. Later events keep their separate horizon.

Every word of revision-2 speech, including “Smart Money Weekend Outlook,” is inside the JSON scenes. Joining scene narration with blank lines exactly reproduces the TXT body and its SHA-256. A fresh build is required after installation; direct edits to just the TXT or JSON break native pairing. The bot does not rewrite an existing approved export.

## Read-only media preflight

```bash
.venv/bin/python scripts/check_weekend_media.py \
  --episode /path/to/weekend_outlook.json \
  --script /path/to/weekend_voiceover.txt \
  --renderer /opt/smart-money-youtube/releases/v2/render_episode.py \
  --output /tmp/weekend_media_preflight.json
```

This validates pairing, metrics, source references and horizons, retrieves the exact native edition from `WEEKEND_STATE_FILE`, re-derives its original proofs and compares the entire export. It checks current weekend/freshness eligibility and requires narration revision 2. It reads the renderer's Python source without importing or executing it. It does not refresh sources, generate audio, render video or upload anything. The optional output must be a new path. The old generic daily-text bridge is not used for weekend reports.

## Reviewed renderer sibling

The saved branded-v2 renderer accepts 2–14 dynamic scenes and the draft-review JSON mode. Its original scene banner, output filename and tags use the daily format. A hash-guarded preparer can create a weekend-capable sibling in the same directory, preserving the daily file and relative asset paths:

```bash
.venv/bin/python scripts/prepare_weekend_renderer.py \
  --renderer /opt/smart-money-youtube/releases/v2/render_episode.py
```

It writes `weekend_render_episode.py` only for the exact reviewed source, supports repeat preparation of the same output and holds on unknown edits. The sibling supplies a WEEKEND OUTLOOK banner, weekend filename/tags, and source edition/narration identifiers in video metadata. It retains daily defaults when explicitly given daily data. Preparing it does not run it. Run the media preflight again with the sibling's path to inspect its compatibility.

The read-only compatibility result is `PREVIEW_COMPATIBLE` for the reviewed sibling. `paid_production_ready` remains false: human media review and the deployed wrappers still need checking. Existing daily company-motion overlays, daily price manifests and daily preparation workers should not be assumed to target the weekend's seven scenes. The preparer preserves unknown customized renderers for review.

## Validation

`python scripts/check_weekend_narration.py` and `--windows-socketpair` cover narration, legacy hashes, native record binding, stale/tampered exports, renderer preparation and actual renderer orchestration. Speech, FFmpeg and network calls are disabled in those orchestration tests. The tests assert that every narration word reaches the speech interface, the weekend banner/filename are selected, API calls do not occur and daily defaults remain available. A successful preflight is not a claim that paid audio, a finished video or an upload has been produced.
