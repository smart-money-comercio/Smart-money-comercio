"""Export a current PASS Weekend Outlook; no refresh, audio generation or upload."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from src.intelligence import weekend_store
from src.reports.weekend_outlook import episode


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True,type=Path,help="New .json path; a matching plain .txt script is also written")
    args=parser.parse_args(argv)
    try:
        record=weekend_store.latest()
        if record is None:raise ValueError("No Weekend Outlook; run /weekend first")
        packet=episode(record,datetime.now(timezone.utc))
        target=args.output.resolve();script=target.with_suffix(".txt")
        if target.suffix.lower()!=".json":raise ValueError("Output must end in .json")
        if target.exists() or script.exists():raise ValueError("Output already exists; choose a new filename")
        target.parent.mkdir(parents=True,exist_ok=True);created=[]
        try:
            for path,text in ((target,json.dumps(packet,ensure_ascii=False,indent=2)+"\n"),(script,record["voiceover"]["script"]+"\n")):
                with path.open("x",encoding="utf-8",newline="\n") as stream:
                    created.append(path);stream.write(text)
        except OSError:
            for path in created:path.unlink(missing_ok=True)
            raise
        print("Weekend draft JSON: "+str(target))
        print("Narration: "+str(script))
        print("Review edition_type weekend_outlook adapter support before media production.")
        return 0
    except (ValueError,OSError,RuntimeError) as error:
        print("Weekend export stopped: "+str(error),file=sys.stderr);return 1


if __name__=="__main__":raise SystemExit(main())
