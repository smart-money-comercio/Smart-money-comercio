"""Read-only native weekend TXT/JSON preflight; optionally inspect renderer source."""

import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from src.intelligence import weekend_store
from src.reports import weekend_outlook,weekend_media_contract as contract


def preflight(packet,script,now=None,renderer=None):
    summary=contract.validate_packet(packet,script)
    record=weekend_store.read_record(packet["bot_edition_id"])
    if record is None:raise ValueError("No matching native weekend record; use the bot's own state and latest paired exports")
    expected=weekend_outlook.episode(record,now or datetime.now(timezone.utc))
    if expected!=packet:raise ValueError("The JSON differs from the native, source-checked bot edition")
    if packet.get("weekend_narration_revision")!=2:raise ValueError("Refresh and re-export to use weekend narration revision 2")
    summary.update(validation_scope="native_edition_and_pairing",native_record="PASS",review_required=True,paid_production_ready=False)
    if renderer is not None:summary["renderer"]=contract.inspect_renderer(renderer)
    else:summary["renderer"]={"status":"NOT_CHECKED","paid_production_ready":False}
    return summary


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode",required=True,type=Path)
    parser.add_argument("--script",required=True,type=Path)
    parser.add_argument("--renderer",type=Path,help="Inspect this Python source without importing or executing it")
    parser.add_argument("--output",type=Path,help="Optional new preflight JSON path")
    args=parser.parse_args(argv)
    try:
        if args.episode.stat().st_size>contract.MAX_BYTES or args.script.stat().st_size>contract.MAX_BYTES:raise ValueError("Input exceeds its bound")
        packet=json.loads(args.episode.read_text(encoding="utf-8-sig"))
        summary=preflight(packet,args.script.read_text(encoding="utf-8-sig"),renderer=args.renderer)
        text=json.dumps(summary,ensure_ascii=False,indent=2)+"\n"
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            with args.output.open("x",encoding="utf-8",newline="\n") as file:file.write(text)
        print(text.strip())
        print("NATIVE WEEKEND PREFLIGHT: PASS. Video branding/wrapper review remains required; no audio, render or upload was started.")
        return 0
    except (OSError,ValueError,TypeError,KeyError,AttributeError) as error:
        print("HOLD: "+str(error),file=sys.stderr);return 1


if __name__=="__main__":raise SystemExit(main())
