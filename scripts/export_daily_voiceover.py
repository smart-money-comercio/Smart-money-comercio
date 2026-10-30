"""Export a recorded news edition to the existing Smart Money YouTube renderer."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.intelligence.news_editor_store import read_editions
from src.reports.daily_voiceover import episode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--latest", action="store_true", help="Use the newest recorded edition")
    selection.add_argument("--edition", help="Use an exact recorded edition ID")
    parser.add_argument("--output", required=True, type=Path, help="New episode JSON path; a matching .txt script is also written")
    args = parser.parse_args(argv)
    try:
        if args.output.suffix.lower() != ".json": raise ValueError("Output must end in .json")
        records = read_editions(limit=1 if args.latest else 200)
        record = next((row for row in records if args.latest or row["id"] == args.edition), None)
        if record is None: raise ValueError("No matching edition; run /rundailyagent after installing this update")
        data = episode(record, datetime.now(timezone.utc))
        target = args.output.resolve(); script_path = target.with_suffix(".txt")
        if target.exists() or script_path.exists(): raise ValueError("Output already exists; choose a new filename")
        target.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation protects an existing export. If either write fails,
        # remove only files created by this invocation.
        created = []
        try:
            for path, text in ((target,json.dumps(data,ensure_ascii=False,indent=2)+"\n"),
                               (script_path,record["voiceover"]["script"]+"\n")):
                with path.open("x",encoding="utf-8",newline="\n") as file:
                    created.append(path); file.write(text)
        except OSError:
            for path in created: path.unlink(missing_ok=True)
            raise
        print("Episode JSON: " + str(target))
        print("ElevenLabs script: " + str(script_path))
        print("Draft ready for the existing renderer; no audio generated or video uploaded.")
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        print("Export stopped: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__": raise SystemExit(main())
