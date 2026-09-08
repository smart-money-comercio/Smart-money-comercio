import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.jobs.source_refresh_job import format_source_refresh_result, run_source_refresh


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Smart Money AI Source Refresh Engine.")
    parser.add_argument("--dry-run", action="store_true", help="Run without live StockAnalysis refresh.")
    args = parser.parse_args()

    result = run_source_refresh(dry_run=args.dry_run)
    print(format_source_refresh_result(result))

    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
