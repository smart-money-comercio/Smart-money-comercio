# Smart Money narration and YouTube export

Each new daily news edition records a separate, tightened spoken script after its source and editorial checks pass. It opens with the takeaway, gives the dated market snapshot, covers admitted developments and relevant company moves, and ends with concrete follow-up checks. The spoken companion skips sector-only company filler, repeated headline attribution, operational timestamps, URLs and bot commands. The text brief and decision log retain the full evidence.

Numbers, percentages, currencies, dates, clocks and common acronyms are written as spoken English. Contract ceilings, proposed deals, test milestones, IPO stages, reporting periods and unverified causes remain qualified. The script uses plain punctuation, without SSML or voice-model-specific tags. Estimates use 160 words per minute; actual audio duration depends on the chosen voice. The companion requires at least 180 editorial spoken words and a 45–80-word market segment. If a thin edition misses those limits, its voice export is held rather than padded with invented news.

## Get the script

After installing on the machine running the bot, run `/rundailyagent`, then `/voiceover`. The latter downloads `smart_money_voiceover.txt` from the recorded edition. `/editorstatus` reports the spoken word count and estimated duration. The command performs no source refresh, model request, ElevenLabs call or channel send. Editions built before this update need a new daily run.

Paste the TXT contents into ElevenLabs using the licensed voice already configured for the project. Keep the text file separate from the report header and evidence links; those are not part of the narration.

## Export for the existing YouTube renderer

Run this on the bot host, where its current editorial database lives. Pulling Git on Windows does not copy Ubuntu's report history.

```bash
cd /opt/smart-money-comercio
sudo -u smartmoney .venv/bin/python scripts/export_daily_voiceover.py --latest --output /tmp/smart_money_episode.json
```

The export writes a JSON episode and a matching `.txt` narration. Choose a different filename for a later export; existing files are never overwritten. An exact recorded ID can be selected with `--edition ID` in place of `--latest`. Both modes require an edition generated within the last eight hours. The export rechecks the source report hashes, original editorial evidence and deterministic narration; it never silently falls back to an older edition or refreshes the sources.

Copy both files to the existing `Smart_Money_YouTube_Branded_Starter_v2` folder on Windows. Its renderer accepts this JSON directly; the older `bot_edition_bridge.py` step is not needed for this spoken companion.

```powershell
Set-Location "C:\Users\josej\Smart_Money_YouTube_Branded_Starter_v2"
python render_episode.py --episode .\smart_money_episode.json --out .\output\voice_ready
```

That final command uses the renderer's existing ElevenLabs key, licensed voice ID, model and artwork, and incurs its normal voice-generation charges. This bot update does not call ElevenLabs itself or change those settings. Scene narration and caption text are identical. The existing renderer estimates caption timings, so check synchronization against the actual audio before publishing. The JSON remains `draft_review_required`; exporting and rendering do not upload a video.

The JSON contains scene headings, short visual bullets, narration, source references, the originating edition ID and report/script hashes. Original company schedule notices and dated earnings-context sources travel with the export. Market and macro-calendar statements remain bound to the frozen report; detailed evidence stays in `/storylog`, `/calendar` and `/fullreport`. No new API dependency or database migration is required. Existing editions, rankings and alert delivery receipts are preserved.

## Offline checks

```text
python scripts/check_daily_voiceover.py
python scripts/check_daily_voiceover.py --windows-socketpair
```
