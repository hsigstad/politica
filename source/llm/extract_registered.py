"""Driver: registered-slate estimulado extraction for post-deadline polls.

INTENT. For 2024 mayoral polls registered AFTER the candidacy-registration
deadline, drive vote-share extraction off the official TSE slate instead of
the fuzzy name-based join. Builds the per-município registered slate from
build/clean/candidato.csv, injects it into the prompt via
poll_relatorio_registered.extract_registered, validates that the returned
candidate set matches the slate EXACTLY in code, maps each matched número
de urna directly to politico_id, and writes a long parquet keyed by
(protocol, politico_id) — no name-join, no scenario-choice step. Spec:
projects/poll-sponsor-bias/docs/notes/extraction-registered-slate-redesign.md.

REASONING. Additive: new output build/llm/poll_relatorio_registered_2024.parquet;
the existing poll_relatorio_2024.parquet path is untouched. Only polls with
date_registered > the deadline qualify — after it the municipal slate is
final, so the matching estimulado scenario is well defined (post-deadline
relatórios must list all registered candidates or risk impugnation).

ASSUMES.
  - Join key: poll_2024.muni_code_tse (int) == int(candidato.municipio_id).
    Verified 3477/3477 municipalities on 2026-07-15 (candidato.municipio_id
    carries a '.0' float suffix — normalise before joining).
  - candidato filters: year=='2024.0', office=='PREFEITO', round=='1.0'.
  - NUMERO_CAND is a float-string ('12.0') → normalise to int-string ('12').
  - Slate candidacy status: the exact-match criterion is strict, so which
    statuses count as "on the ballot" is a calibration knob (ON_BALLOT_STATUS).
    Default = effectively-on-ballot set; RENUNCIA / FALECIMENTO / INDEFERIDO
    excluded. --dry-run reports slate coverage so the knob can be tuned
    against real match rates before spending on the API.

Usage:
    # Dry run — build slates, report PDF+slate coverage, NO API calls:
    BASE_DIR=/path/to/politica \
    PYTHONPATH=/path/to/llmkit:/path/to/politica/source/llm \
      python source/llm/extract_registered.py --year 2024 --dry-run --limit 20

    # Live smoke test on a few PDFs (real API):
    ... python source/llm/extract_registered.py --year 2024 --limit 10

    # Full post-deadline run:
    ... python source/llm/extract_registered.py --year 2024
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

# pandas 3.0 infer_string breaks .astype(str) over NaN and dtype-changing
# .loc assignment in this venv (reference_pandas_3_infer_string). Disable it.
pd.set_option("future.infer_string", False)

BASE_DIR = Path(os.environ["BASE_DIR"])
BUILD_DIR = BASE_DIR / "build"
PDFS_BASE = BUILD_DIR / "scrape" / "tse_relatorio"

REG_DEADLINE = pd.Timestamp("2024-08-15")   # TSE 2024 candidacy-registration deadline

# Candidacy statuses treated as "on the ballot" for the registered slate.
# The exact-slate-match criterion is strict, so this set is the primary
# calibration knob — widen/narrow it against --dry-run / smoke match rates.
ON_BALLOT_STATUS = {
    "DEFERIDO",
    "DEFERIDO COM RECURSO",
    "INDEFERIDO EM PRAZO RECURSAL OU COM RECURSO",
    "AGUARDANDO JULGAMENTO",
}


# ── Slate construction ───────────────────────────────────────────────

def _int_str(series: pd.Series) -> pd.Series:
    """'12.0' / '1007.0' → '12' / '1007' (drop float suffix); NaN → <NA>."""
    return series.astype(float).astype("Int64")


def load_slates(year: int, statuses: set[str]) -> dict[int, pd.DataFrame]:
    """Return {muni_code_tse: slate_df} where slate_df has one row per
    on-ballot registered prefeito candidate: politico_id, nome_urna, party,
    numero_cand (clean int-string). Dedupes on (muni, número), preferring
    DEFERIDO."""
    cols = ["year", "office", "round", "status", "municipio_id",
            "politico_id", "nome_urna", "party", "NUMERO_CAND"]
    c = pd.read_csv(BASE_DIR / "build" / "clean" / "candidato.csv",
                    usecols=cols, dtype=str)
    c = c[(c.year == f"{year}.0") & (c.office == "PREFEITO")
          & (c["round"] == "1.0")].copy()
    c["muni_code_tse"] = _int_str(c.municipio_id)
    c["numero_cand"] = _int_str(c.NUMERO_CAND).astype("string")
    c = c[c.status.isin(statuses)]
    # Prefer DEFERIDO on any (muni, número) collision, then drop dups.
    c["_pref"] = (c.status != "DEFERIDO").astype(int)
    c = (c.sort_values("_pref")
           .drop_duplicates(["muni_code_tse", "numero_cand"], keep="first"))
    slates: dict[int, pd.DataFrame] = {}
    for muni, g in c.groupby("muni_code_tse"):
        slates[int(muni)] = g[["politico_id", "nome_urna", "party",
                               "numero_cand"]].reset_index(drop=True)
    return slates


def slate_json(slate: pd.DataFrame) -> str:
    return json.dumps(
        [{"numero": r.numero_cand, "nome_urna": r.nome_urna, "party": r.party}
         for r in slate.itertuples()],
        ensure_ascii=False,
    )


# ── Poll set ─────────────────────────────────────────────────────────

def load_polls(year: int) -> pd.DataFrame:
    """Post-deadline mayoral polls that have a relatório PDF on disk."""
    p = pd.read_parquet(BUILD_DIR / "clean" / f"poll_{year}.parquet")
    p = p[p.cargo.str.contains("Prefeito", na=False)
          & (p.date_registered > REG_DEADLINE)].copy()
    pdf_dir = PDFS_BASE / str(year)
    p["pdf_path"] = p.protocol.map(lambda x: pdf_dir / f"{x}.pdf")
    p["has_pdf"] = p.pdf_path.map(lambda x: x.exists())
    return p


# ── Code-side slate reconciliation ───────────────────────────────────

def reconcile(parsed, slate: pd.DataFrame) -> dict:
    """Reconcile the model's fill-the-slate output against the slate, in
    code. Returns coverage diagnostics; número→politico_id is an EXACT map
    from the slate (no fuzzy name match). We do not reject on partial
    coverage — a slate candidate absent from the scenario is a legitimate
    null, not a failure."""
    want = set(slate.numero_cand)
    got = {e.numero_cand for e in parsed.estimates}
    with_pct = {e.numero_cand for e in parsed.estimates if e.percent is not None}
    # Candidate shares can't sum past ~100 (undecided/blank take the rest).
    # A sum well over 100 means the model read the wrong table (e.g. a
    # cross-tab column or two merged scenarios) — a catchable quality flag.
    pct_sum = sum(e.percent for e in parsed.estimates
                  if e.percent is not None and e.numero_cand in want)
    return {
        "in_slate": got & want,          # echoed números that are real slate members
        "off_slate": got - want,         # echoed números NOT in the slate (model error)
        "missing": want - got,           # slate members the model omitted entirely
        "n_filled": len(with_pct & want),
        "pct_sum": round(pct_sum, 1),
        "suspect_sum": pct_sum > 105,    # >105 ⇒ impossible ⇒ likely wrong table
    }


# ── Main ─────────────────────────────────────────────────────────────

def run(args) -> None:
    statuses = ON_BALLOT_STATUS
    print(f"Building slates ({args.year}, statuses={sorted(statuses)}) ...")
    slates = load_slates(args.year, statuses)
    polls = load_polls(args.year)

    has_slate = polls.muni_code_tse.map(lambda m: m in slates)
    eligible = polls[polls.has_pdf & has_slate].copy()
    print(f"post-deadline mayoral polls: {len(polls)}  "
          f"with PDF: {int(polls.has_pdf.sum())}  "
          f"with PDF+slate: {len(eligible)}")
    if args.limit:
        eligible = eligible.head(args.limit)

    if args.dry_run:
        # Report slate sizes without touching the API.
        sizes = eligible.muni_code_tse.map(lambda m: len(slates[m]))
        print(f"[dry-run] would extract {len(eligible)} polls; "
              f"slate size median={sizes.median()} max={sizes.max()}")
        print(eligible[["protocol", "uf", "municipality",
                        "date_registered"]].head(10).to_string(index=False))
        return

    from openai import OpenAI
    from poll_relatorio_registered import CANONICAL_CACHE_DIR, MODEL, extract_registered

    vision = args.engine == "vision"
    if vision:
        from poll_relatorio_vision import CACHE_DIR as CANONICAL_CACHE_DIR
        from poll_relatorio_vision import extract_vision

    def call(row, slate):
        common = dict(protocol=row.protocol, pdf_path=row.pdf_path,
                      slate_json=slate_json(slate), municipality=row.municipality,
                      uf=row.uf, client=client, model=args.model or MODEL,
                      reextract=args.reextract)
        return extract_vision(**common) if vision else extract_registered(**common)

    client = OpenAI()
    print(f"engine: {args.engine}  cache: {CANONICAL_CACHE_DIR}  "
          f"model: {args.model or MODEL}")
    rows: list[dict] = []
    counts = {"scenario": 0, "no_scenario": 0, "image_only": 0, "error": 0}
    t0 = time.monotonic()

    for i, row in enumerate(eligible.itertuples(), 1):
        slate = slates[row.muni_code_tse]
        num2pid = dict(zip(slate.numero_cand, slate.politico_id))
        num2party = dict(zip(slate.numero_cand, slate.party))
        try:
            r = call(row, slate)
        except Exception as exc:  # noqa: BLE001 — log + continue over the batch
            counts["error"] += 1
            print(f"  ERR {row.protocol}: {exc!r}")
            continue
        if r is None:
            counts["image_only"] += 1
            continue
        if not r.valid:
            counts["error"] += 1
            print(f"  INVALID {row.protocol}: {r.validation_errors}")
            continue
        parsed = r.parsed
        if not parsed.scenario_found:
            counts["no_scenario"] += 1
            continue
        counts["scenario"] += 1
        rec = reconcile(parsed, slate)
        # One row per slate candidate the model returned. politico_id is an
        # EXACT map from the slate número — off-slate números map to None
        # and are kept as a visible data-quality flag, not silently dropped.
        for e in parsed.estimates:
            rows.append({
                "protocol": row.protocol, "muni_code_tse": row.muni_code_tse,
                "uf": row.uf, "municipality": row.municipality,
                "scenario_label": parsed.scenario_label,
                "numero_cand": e.numero_cand,
                "politico_id": num2pid.get(e.numero_cand),   # None ⇒ off-slate
                "on_slate": e.numero_cand in set(slate.numero_cand),
                "nome_urna": e.nome_urna,
                "party": num2party.get(e.numero_cand),
                "percent": e.percent,
                "n_slate": len(slate),
                "n_filled": rec["n_filled"],
                "n_missing": len(rec["missing"]),
                "n_off_slate": len(rec["off_slate"]),
                "pct_sum": rec["pct_sum"],
                "suspect_sum": rec["suspect_sum"],
                "extra_candidates": "; ".join(parsed.extra_candidates),
                "extraction_notes": parsed.extraction_notes,
            })
        if i % 50 == 0 or i == len(eligible):
            print(f"  [{i}/{len(eligible)}] {counts} ({time.monotonic()-t0:.0f}s)")

    print(f"\nCounts: {counts}")
    if not rows:
        print("No rows assembled.")
        return
    stem = "poll_relatorio_vision" if args.engine == "vision" else "poll_relatorio_registered"
    out = BUILD_DIR / "llm" / f"{stem}_{args.year}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_parquet(out, index=False)
    polls = df.protocol.nunique()
    exact = df.groupby("protocol").first().query("n_missing == 0 and n_off_slate == 0").shape[0]
    print(f"Wrote {len(df):,} rows / {polls} polls "
          f"({exact} with full slate coverage, 0 off-slate) → {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, choices=[2024], default=2024)
    ap.add_argument("--engine", choices=["text", "vision"], default="text",
                    help="text = pdftotext + LLM; vision = render page + vision LLM.")
    ap.add_argument("--model", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--reextract", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="build slates + report coverage, no API calls.")
    args = ap.parse_args()
    if not PDFS_BASE.exists():
        sys.exit(f"No PDF base at {PDFS_BASE}")
    run(args)


if __name__ == "__main__":
    main()
