import argparse
import os
from pathlib import Path

import pandas as pd

from classifier import SchemaError, api_key, load_schema
from runner import run

BASE = Path(__file__).parent


def main():
    p = argparse.ArgumentParser(description="Classify a CSV of records using a schema.")
    p.add_argument("--data", default=BASE / "data" / "reviews.csv")
    p.add_argument("--schema", default=BASE / "schemas" / "review_schema.json")
    p.add_argument("--out", default=BASE / "data" / "classified.csv")
    p.add_argument("--model", default=os.getenv("PRIMARY_MODEL", "nvidia/nemotron-3-super-120b-a12b:free"))
    p.add_argument("--fallback", default=os.getenv("FALLBACK_MODEL", ""))
    p.add_argument("--limit", type=int)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--rpm", type=int, default=18, help="max requests per minute, 0 = no limit")
    p.add_argument("--batch", type=int, default=10, help="records per request (chat models only; decision models use 1)")
    args = p.parse_args()

    if not api_key():
        raise SystemExit("OPENROUTER_API_KEY is not set (put it in .env)")

    try:
        schema = load_schema(Path(args.schema).read_text(encoding="utf-8"))
        source = Path(args.out) if Path(args.out).exists() else Path(args.data)  # resume a previous run
        df = pd.read_csv(source, dtype=str).fillna("")
    except (SchemaError, OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as e:
        raise SystemExit(f"Could not load the input files: {e}")
    out = Path(args.out)

    models = [args.model] + ([args.fallback] if args.fallback else [])

    def progress(n, total, current):
        if n % 10 == 0 or n == total:
            print(f"{n}/{total}")
            current.to_csv(out, index=False)

    try:
        df, stats = run(df, schema, models, args.workers, args.rpm, progress, args.limit, args.batch)
    except SchemaError as e:
        raise SystemExit(f"This schema cannot be used with {args.model}: {e}")
    df.to_csv(out, index=False)

    print(f"done {stats['done']}, failed {stats['failed']}, requests used {stats['requests']}")
    print(f"{stats['elapsed_s']:.1f}s total, {stats['records_per_s']:.2f} records/s, "
          f"avg latency {stats['avg_latency_s']:.2f}s, p95 {stats['p95_latency_s']:.2f}s")
    if stats["cost"]:
        print(f"cost ${stats['cost']:.6f} (about ${stats['cost'] / max(stats['done'], 1) * 1000:.4f} per 1,000 reviews)")

    if stats["stopped"]:
        print(f"\nStopped early: {stats['stopped']}")
        print(f"{stats['done']} reviews are saved in {out}. Run the same command again to continue.")


if __name__ == "__main__":
    main()
