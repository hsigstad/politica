"""Extract per-candidate vote intentions from TSE relatório PDFs.

Pipeline-level driver: walks the PDF set, calls the llmkit-backed
extraction wrapper in `poll_relatorio.py`, and assembles the cached
results into a long-format parquet.

Migrated to llmkit 2026-06-01 (cache + Pydantic validation + audit
metadata are now standardized). The pre-llmkit in-house cache format
(`{PROTOCOL}.json` with a top-level `status` and a nested `extraction`)
is read transparently by the wrapper's legacy fallback — including an
earlier 111-protocol pilot kept under a legacy cache directory.

Reads PDFs from build/scrape/tse_relatorio/{year}/{PROTOCOLO}.pdf,
caches one JSON per protocol at build/llm/poll_relatorio/, writes the
combined build/llm/poll_relatorio_{year}.parquet at the end.

Schema is intentionally narrow: we only ask the LLM for what's NEW in
the PDF (per-candidate vote intentions per scenario), since institute,
dates, sample size, municipality, methodology are already in the TSE
registration CSV and join by NR_PROTOCOLO_REGISTRO.

Image-only PDFs (where pdftotext returns near-zero chars) are skipped.
An OCR fallback is left for a future pass.

Usage:
    # Live run, all UFs except SP (SP was extracted separately):
    python source/llm/poll_extract.py --year 2024 --exclude-states SP

    # Smoke test (PDF-free) — re-validate the 111-protocol legacy pilot
    # against the current schema and assemble a parquet without
    # touching PDFs or the OpenAI API:
    python source/llm/poll_extract.py --year 2024 --validate-cached

    # Small batch on one UF (e.g. for spot-checks):
    python source/llm/poll_extract.py --year 2024 --states AC --limit 10
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

from poll_relatorio import (
    CACHE,
    CANONICAL_CACHE_DIR,
    LEGACY_CACHE_DIRS,
    MODEL,
    extract_poll_relatorio,
    validate_cached_only,
)

load_dotenv()
BASE_DIR = Path(os.environ["BASE_DIR"])
BUILD_DIR = BASE_DIR / "build"
PDFS_BASE = BUILD_DIR / "scrape" / "tse_relatorio"
# Optional fallback PDF directory (e.g. a pre-migration stash), used only
# when PDFS_BASE/<year> is empty. Configure via PDF_FALLBACK_DIR.
_pdf_fallback = os.environ.get("PDF_FALLBACK_DIR")
PDF_FALLBACK_DIR = Path(_pdf_fallback) if _pdf_fallback else None


# ── PDF discovery and state filtering ────────────────────────────────

def discover_pdfs(year: int) -> list[Path]:
    for root in (PDFS_BASE, PDF_FALLBACK_DIR):
        if root is None:
            continue
        d = root / str(year)
        if d.exists():
            pdfs = sorted(d.glob("*.pdf"))
            if pdfs:
                return pdfs
    return []


def filter_states(
    pdfs: list[Path],
    include: list[str] | None,
    exclude: list[str] | None,
) -> list[Path]:
    """TSE protocol filenames start with the 2-letter UF (e.g.
    AC094012020.pdf → state AC). Filter the list accordingly."""
    if not include and not exclude:
        return pdfs
    inc = {s.upper() for s in (include or [])}
    exc = {s.upper() for s in (exclude or [])}
    def state(p: Path) -> str:
        return p.stem[:2].upper()
    out = []
    for p in pdfs:
        st = state(p)
        if inc and st not in inc:
            continue
        if exc and st in exc:
            continue
        out.append(p)
    return out


# ── Assemble ─────────────────────────────────────────────────────────

def assemble_long_table(
    year: int,
    include_legacy_pilot: bool = True,
) -> pd.DataFrame:
    """Collect every successfully-extracted entry (new-format cache +
    legacy pilot files) into a long-format DataFrame: one row per
    (protocol, scenario, candidate). Records that fail validation
    against PollRelatorio are dropped with a warning printed."""
    rows: list[dict] = []
    seen_protocols: set[str] = set()
    bad = 0

    def consume(protocol: str, extraction: dict, source: str):
        nonlocal bad
        from llmkit.extract import _validate
        from schemas import PollRelatorio
        parsed, valid, errors = _validate(extraction, PollRelatorio)
        if not valid:
            bad += 1
            return
        for s in parsed.scenarios:
            for c in s.candidates:
                rows.append({
                    "protocol": protocol,
                    "tse_protocol_display": parsed.tse_protocol,
                    "scenario_type": s.scenario_type,
                    "scenario_label": s.scenario_label,
                    "candidate_name": c.candidate_name,
                    "party": c.party,
                    "percent": c.percent,
                    "extraction_notes": parsed.extraction_notes,
                    "source": source,
                })

    # 1. New-format llmkit entries. iter_entries() returns BOTH new-format
    # (envelope has _cache_meta) AND politica-legacy files (top-level
    # {status, model, ..., extraction:{...}}) — for the latter llmkit
    # treats the whole file as the extraction, which won't validate
    # against PollRelatorio. Filter to entries that actually carry
    # _cache_meta (signaled by a non-empty entry.meta); the legacy
    # loop below unwraps the rest correctly.
    for entry in CACHE.iter_entries():
        if not entry.meta:
            continue
        protocol = entry.meta.get("doc_id") or entry.key
        if protocol in seen_protocols:
            continue
        seen_protocols.add(protocol)
        consume(protocol, entry.extraction, source="llmkit")

    # 2. Legacy {PROTOCOL}.json entries (pilot + any pre-migration files)
    if include_legacy_pilot:
        import json
        for legacy_dir in LEGACY_CACHE_DIRS:
            if not legacy_dir.exists():
                continue
            for jp in sorted(legacy_dir.glob("*.json")):
                protocol = jp.stem
                if protocol in seen_protocols:
                    continue
                try:
                    data = json.loads(jp.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if "_cache_meta" in data:
                    continue  # would have been picked up via CACHE.iter_entries
                if data.get("status") != "ok":
                    continue
                extraction = data.get("extraction")
                if not isinstance(extraction, dict):
                    continue
                seen_protocols.add(protocol)
                consume(protocol, extraction, source="legacy_pilot")

    if bad:
        print(f"WARN: {bad} cached entries failed schema validation "
              f"(dropped from parquet).")
    return pd.DataFrame(rows)


# ── Main ─────────────────────────────────────────────────────────────

def run_live(args) -> tuple[dict, int, int]:
    pdfs = discover_pdfs(args.year)
    pdfs = filter_states(pdfs, args.states, args.exclude_states)
    if args.limit:
        pdfs = pdfs[:args.limit]
    if not pdfs:
        sys.exit(
            f"No PDFs to process under {PDFS_BASE/str(args.year)} after "
            f"state filter (include={args.states}, exclude={args.exclude_states}). "
            "Run source/scrape/tse_relatorio.py first to populate PDFs."
        )
    print(f"PDFs to process: {len(pdfs)}  cache: {CANONICAL_CACHE_DIR}  "
          f"model: {args.model}  workers: {args.workers}")

    client = OpenAI()
    counts = {"ok": 0, "cached": 0, "image_only": 0, "error": 0}
    tok_in = tok_out = 0
    t0 = time.monotonic()

    def one(pdf: Path):
        protocol = pdf.stem
        try:
            r = extract_poll_relatorio(
                protocol=protocol, pdf_path=pdf, client=client,
                model=args.model, reextract=args.reextract,
            )
        except Exception as exc:
            return protocol, "error", repr(exc), {}
        if r is None:
            return protocol, "image_only", None, {}
        status = "cached" if r.cached else "ok"
        return protocol, status, None, (r.usage or {})

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(one, pdf): pdf for pdf in pdfs}
        for i, fut in enumerate(as_completed(futs), 1):
            protocol, status, err, usage = fut.result()
            counts[status] = counts.get(status, 0) + 1
            tok_in += usage.get("prompt_tokens", 0)
            tok_out += usage.get("completion_tokens", 0)
            if status == "error":
                print(f"  ERR {protocol}: {err}")
            if i % 100 == 0 or i == len(pdfs):
                cost = tok_in / 1e6 * 0.15 + tok_out / 1e6 * 0.60
                dt = time.monotonic() - t0
                print(f"  [{i}/{len(pdfs)}] {counts} "
                      f"tokens={tok_in:,}/{tok_out:,} ~${cost:.3f} "
                      f"({dt:.0f}s)")

    print(f"\nLive-run counts: {counts}")
    return counts, tok_in, tok_out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, choices=[2020, 2024], required=True)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--limit", type=int, default=None,
                    help="cap the number of PDFs (for spot-checks).")
    ap.add_argument("--states", nargs="+", default=None,
                    help="Include only these UFs (2-letter codes).")
    ap.add_argument("--exclude-states", nargs="+", default=None,
                    help="Skip these UFs (2-letter codes). E.g. SP if "
                         "already extracted on another host.")
    ap.add_argument("--reextract", action="store_true",
                    help="ignore cache and re-extract.")
    ap.add_argument("--workers", type=int, default=8,
                    help="parallel API workers.")
    ap.add_argument("--validate-cached", action="store_true",
                    help="PDF-free: re-validate every cached entry (incl. "
                         "legacy pilot) against the current schema and "
                         "write the assembled parquet. No LLM calls.")
    args = ap.parse_args()

    if not args.validate_cached:
        run_live(args)

    out_parquet = BUILD_DIR / "llm" / f"poll_relatorio_{args.year}.parquet"
    df = assemble_long_table(args.year, include_legacy_pilot=True)
    if df.empty:
        print("No successful extractions to assemble.")
        return
    out_parquet.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_parquet, index=False)
    print(f"\nAssembled {len(df):,} candidate-scenario rows from "
          f"{df['protocol'].nunique()} polls → {out_parquet}")
    print(f"source distribution: "
          f"{df['source'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()
