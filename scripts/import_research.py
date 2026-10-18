"""Import reviewed public research, or extract a PDF into a private draft."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.intelligence.research_ingestion import MAX_SOURCE_BYTES, create_draft, import_manifest
from src.intelligence.research_store import ResearchError, import_document, read_documents


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", type=Path, help="Reviewed public JSON manifest.")
    parser.add_argument("--source", type=Path, help="Validate the manifest against this exact PDF.")
    parser.add_argument("--seed", action="store_true", help="Validate/synchronize the bundled reviewed public research.")
    parser.add_argument("--draft", type=Path, help="Extract a PDF into an ignored private draft; never publishes claims.")
    parser.add_argument("--period", help="Quarter to validate, for example 'Q3 2026'.")
    args = parser.parse_args(argv)
    if sum([bool(args.manifest), args.seed, bool(args.draft)]) != 1:
        parser.error("Choose one manifest, --seed, or --draft PDF.")
    if args.source and not args.manifest:
        parser.error("--source accompanies a reviewed manifest.")
    try:
        if args.seed:
            documents = read_documents()
            for document in documents:
                import_document(document)
            print(f"Document Research: {len(documents)} public source(s) validated; raw PDFs and account data excluded.")
        elif args.draft:
            import hashlib
            if args.draft.stat().st_size > MAX_SOURCE_BYTES:
                raise ResearchError("Expected a PDF source no larger than 50 MiB.")
            token = hashlib.sha256(args.draft.read_bytes()).hexdigest()[:16]
            output = PROJECT_ROOT / "data/research/drafts" / (token + ".json")
            result = create_draft(args.draft, output, args.period)
            print(f"Private draft created: {output}")
            print(f"Pages: {result['pages']}; completeness: {result['completeness']}; source issues: {result['issues']}.")
            print("No public claims imported. Prepare a reviewed manifest using the documented schema.")
        else:
            result = import_manifest(args.manifest, args.source)
            print(f"Document Research: {'updated' if result['changed'] else 'already imported'}; {result['claims']} claim(s).")
        return 0
    except (ResearchError, OSError) as error:
        # Source text, account values and full parser exceptions must not enter shared logs.
        detail = str(error) if isinstance(error, ResearchError) else "The input file could not be accessed."
        print("Research import stopped: " + detail, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
