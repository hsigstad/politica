# INTENT: stage-1 driver — compute the per-dataset summary JSON cache the portal
# reads, one file per DATASETS entry.
# REASONING: the cache is committed to git (it lives outside the gitignored
# build/), so the site builds on a machine without the clean tables. Cache-first
# by default; --force recomputes all, --only <id> does one. A dataset whose file
# is missing is skipped (not every host stages every table).
# ASSUMES: config.DATASETS/CACHE_DIR and compute.compute_stats define the work.
"""
Compute summary statistics for all registered politica datasets.

    python3 -m source.summary.build_all              # refresh only new entries
    python3 -m source.summary.build_all --force      # recompute all
    python3 -m source.summary.build_all --only candidato
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback

from .compute import compute_stats
from .config import CACHE_DIR, DATASETS, DatasetConfig


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--force", action="store_true",
                    help="Recompute even when a cache JSON exists.")
    ap.add_argument("--only", metavar="ID", help="Recompute a single dataset.")
    args = ap.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    targets = [d for d in DATASETS if not args.only or d.id == args.only]
    if args.only and not targets:
        print(f"No dataset with id={args.only!r}", file=sys.stderr)
        return 2

    n_ok = n_skip = n_err = 0
    for cfg in targets:
        out = CACHE_DIR / f"{cfg.id}.json"
        if out.exists() and not args.force and not args.only:
            n_skip += 1
            continue
        if not cfg.path.exists():
            print(f"  SKIP {cfg.id} (file missing: {cfg.path})")
            n_skip += 1
            continue
        try:
            print(f"  {cfg.id} ...", end=" ", flush=True)
            stats = compute_stats(cfg)
            out.write_text(json.dumps(stats, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            grain = stats.get("grain_check")
            badge = "" if not grain else (" grain:ok" if grain.get("is_unique")
                                          else " grain:DUP")
            print(f"{stats['row_count']:,} rows x {stats['col_count']} cols{badge}")
            n_ok += 1
        except Exception as e:
            print(f"ERR {cfg.id}: {e}")
            traceback.print_exc()
            n_err += 1

    print(f"\nDone: {n_ok} computed, {n_skip} skipped, {n_err} errors.")
    return 1 if n_err else 0


if __name__ == "__main__":
    raise SystemExit(main())
