"""Read-only weekend media contract; no rendering, network or paid service calls."""

import ast
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

MAX_BYTES=500000
NY=ZoneInfo("America/New_York")
# The saved branded v2 renderer was inspected without invoking speech or FFmpeg.
REFERENCE_RENDERER_SHA256="2c275c853a087760fe9b916e2ad388bacc16568adc81893ab5863f8c63b000dc"
WEEKEND_RENDERER_SHA256="63d2c82f3b59b3ee96d00bf196391f6fe6b28736148fb11aa481f0f44cb748e6"


def digest(text):
    return sha256(text.encode()).hexdigest()


def clock(value):
    if not isinstance(value,str):raise ValueError("Media clock is missing")
    try:at=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError:at=parsedate_to_datetime(value)
    if at.tzinfo is None:raise ValueError("Media clock has no timezone")
    return at.astimezone(timezone.utc)


def forbidden(value):
    if isinstance(value,dict):
        return any(key in {"source_text","source_excerpt","event_evidence"} or forbidden(item) for key,item in value.items())
    return isinstance(value,list) and any(forbidden(item) for item in value)


def validate_packet(packet,script=None):
    if (not isinstance(packet,dict) or packet.get("edition_type")!="weekend_outlook" or type(packet.get("voiceover_schema")) is not int
            or packet["voiceover_schema"]!=2 or packet.get("mode")!="draft_review_required" or packet.get("review_required") is not True
            or packet.get("contains_synthetic_media") is not True):
        raise ValueError("A native review-only schema-2 Weekend Outlook is required")
    if forbidden(packet):raise ValueError("Original article proof is not a media-export field")
    if len(json.dumps(packet,ensure_ascii=False,allow_nan=False).encode())>MAX_BYTES:raise ValueError("Media packet exceeds its bound")
    at=clock(packet["bot_generated_at"]);start=date.fromisoformat(packet["week_start"]);end=date.fromisoformat(packet["week_end"])
    next_start=date.fromisoformat(packet["next_week_start"]);next_end=date.fromisoformat(packet["next_week_end"])
    local=at.astimezone(NY)
    if (start.weekday()!=0 or end!=start+timedelta(days=4) or next_start!=start+timedelta(days=7)
            or next_end!=start+timedelta(days=11) or local.weekday() not in {5,6} or local.date()-timedelta(days=local.weekday())!=start
            or packet.get("date")!=local.date().isoformat()):
        raise ValueError("Weekend media dates or horizons changed")
    segments=packet.get("segments");sources=packet.get("sources")
    if not isinstance(segments,list) or not 2<=len(segments)<=14 or not isinstance(sources,dict) or len(sources)>40:
        raise ValueError("Weekend media scene/source bounds exceeded")
    for row in segments:
        if (not isinstance(row,dict) or not isinstance(row.get("heading"),str) or not row["heading"].strip()
                or not isinstance(row.get("narration"),str) or not row["narration"].strip()
                or not isinstance(row.get("bullets"),list) or len(row["bullets"])>3
                or not isinstance(row.get("source_ids"),list) or len(row["source_ids"])>12
                or any(not isinstance(key,str) or key not in sources for key in row["source_ids"])):
            raise ValueError("A scene is empty or has unresolved source references")
    revision=packet.get("weekend_narration_revision",1)
    if type(revision) is not int or revision not in {1,2}:raise ValueError("Unknown media narration revision")
    text=("Smart Money Weekend Outlook.\n\n" if revision==1 else "")+"\n\n".join(row["narration"] for row in segments)
    if digest(text)!=packet.get("voiceover_sha256"):raise ValueError("Scene narration does not match the approved script checksum")
    if script is not None and script.removesuffix("\n")!=text:raise ValueError("TXT and JSON narration differ")
    words=len(re.findall(r"\b[\w]+(?:['-][\w]+)*\b",text));quality=packet.get("voiceover_quality",{})
    if (not 300<=words<=1200 or quality.get("status")!="PASS" or quality.get("words")!=words
            or quality.get("words_per_minute")!=160 or quality.get("estimated_seconds")!=round(words*60/160,1)):
        raise ValueError("Narration metrics do not match the script")
    for name,rows in sources.items():
        if not isinstance(name,str) or not isinstance(rows,list) or not 1<=len(rows)<=3:raise ValueError("Malformed media source entry")
        for source in rows:
            p=urlsplit(source["url"])
            if p.scheme!="https" or not p.hostname or p.username or p.password:raise ValueError("Source requires an identified HTTPS publisher")
            if not -60<=(at-clock(source["verified_at"])).total_seconds()<=21600:raise ValueError("Source observation was not current at generation")
            if source.get("published_at") and clock(source["published_at"])>at+timedelta(seconds=60):raise ValueError("Future source publication")
            if name.startswith("market_") and (source.get("baseline_date")!=(start-timedelta(days=3)).isoformat() or source.get("session_date")!=end.isoformat()):
                raise ValueError("Weekly source dates changed")
            if name.startswith("story_") and not start<=clock(source["published_at"]).astimezone(NY).date()<=local.date():raise ValueError("Story is outside the weekly evidence window")
            if name.startswith("calendar_") and not next_start<=clock(source["event_at"]).astimezone(NY).date()<=next_end:raise ValueError("Calendar is outside the coming week")
            if name.startswith("later_") and not next_end<date.fromisoformat(source["event_date"])<=next_end+timedelta(days=14):raise ValueError("Later event is in the wrong horizon")
    return {"status":"PASS","validation_scope":"export_structure_and_pairing","edition_id":packet["bot_edition_id"],
        "narration_revision":revision,"all_spoken_text_in_scenes":revision==2,"segments":len(segments),"source_entries":len(sources),
        "words":words,"estimated_seconds":quality["estimated_seconds"],"voiceover_sha256":digest(text),
        "episode_sha256":digest(json.dumps(packet,sort_keys=True,ensure_ascii=False,separators=(",",":")))}


def inspect_renderer(path):
    path=Path(path)
    if path.stat().st_size>MAX_BYTES:raise ValueError("Renderer source exceeds the inspection bound")
    raw = path.read_bytes()
    # Match the preparer's UTF-8 BOM and universal newline handling.
    source = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    tree = ast.parse(source)
    constants={node.value for node in ast.walk(tree) if isinstance(node,ast.Constant) and isinstance(node.value,str)}
    fingerprint=digest(source)
    known=fingerprint in {REFERENCE_RENDERER_SHA256,WEEKEND_RENDERER_SHA256}
    adapted=fingerprint==WEEKEND_RENDERER_SHA256
    return {"status":"PREVIEW_COMPATIBLE" if adapted else "WEEKEND_BANNER_ADAPTER_REQUIRED" if known else "CUSTOM_RENDERER_REVIEW_REQUIRED",
        "renderer_sha256":sha256(raw).hexdigest(),"known_saved_v2":known,"weekend_adapter":adapted,
        "scene_structure":"2–14 dynamic scenes accepted by the saved v2 renderer" if known else "unverified renderer revision",
        "daily_banner_present":"DAILY MARKET BRIEF" in constants,
        "native_weekend_json_required":True,"daily_text_bridge_supported":False,
        "paid_production_ready":False,
        "next_check":"Review weekend branding and the deployed video wrappers before production; no renderer was executed"}


def adapted_renderer(source):
    if digest(source)!=REFERENCE_RENDERER_SHA256:raise ValueError("Renderer differs from the reviewed v2 source; inspect the deployed customization before adapting it")
    replacements=(
        ('def compose_slide(heading, bullets, output, index, demo=False):',
         'def compose_slide(heading, bullets, output, index, demo=False, edition_label="DAILY MARKET BRIEF"):'),
        ('d.text((1480, 98), "DAILY MARKET BRIEF", font=font(27, True), fill=WHITE)',
         'd.text((1480, 98), edition_label, font=font(27, True), fill=WHITE)'),
        ('compose_slide(seg["heading"], seg.get("bullets") or [], still, i, demo)',
         'compose_slide(seg["heading"], seg.get("bullets") or [], still, i, demo, edition_label="WEEKEND OUTLOOK" if data.get("edition_type") == "weekend_outlook" else "DAILY MARKET BRIEF")'),
        ('final = folder / "Smart_Money_Project_Daily_Brief.mp4"',
         'final = folder / ("Smart_Money_Project_Weekend_Outlook.mp4" if data.get("edition_type") == "weekend_outlook" else "Smart_Money_Project_Daily_Brief.mp4")'),
        ('"tags": ["Smart Money Project", "daily market brief", "investing", "market intelligence"],',
         '"tags": ["Smart Money Project", "weekend outlook" if data.get("edition_type") == "weekend_outlook" else "daily market brief", "investing", "market intelligence"],'),
        ('"source_edition_date": data.get("date"),',
         '"source_edition_date": data.get("date"),\n        "source_edition_type": data.get("edition_type", "daily_brief"),\n        "bot_edition_id": data.get("bot_edition_id"),\n        "voiceover_sha256": data.get("voiceover_sha256"),\n        "weekend_narration_revision": data.get("weekend_narration_revision"),'),
        ('illustrated, branded daily scenes.', 'illustrated, branded research scenes.'))
    for before,after in replacements:
        if source.count(before)!=1:raise ValueError("Reviewed renderer anchor changed")
        source=source.replace(before,after,1)
    compile(source,"weekend_render_episode.py","exec")
    return source
