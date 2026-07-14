"""Clean per-year TSE mayoral poll registry: one row per registered poll
(NR_PROTOCOLO_REGISTRO), with the full set of TSE registration metadata.

INTENT: emit a single canonical poll-level table per year so downstream
cleaners do not re-parse the per-UF TSE registration CSVs.
`poll_response_{year}.py` and `poll_sponsor.py` both used to load and
filter `pesquisa_eleitoral_{year}_*.csv` themselves — now they read
`build/clean/poll_{year}.parquet` instead.

REASONING: the per-UF CSV concat + mayoral filter + protocol dedupe is
the same operation in every consumer; staging it once removes the
duplicated I/O (and the duplicated risk of drift between consumers'
column lists). The output keeps every TSE registration field that any
downstream consumer needs — pollster identity, field dates, sample
size, registry/divulgação dates, price, election code, plus the
optional "own poll" flag `ST_PESQUISA_PROPRIA` where present.

ASSUMES (per year): a registry of mayoral polls is staged at
DATA_DIR/TSE/{year}/pesquisa_eleitoral/ (canonical) or
build/scrape/tse_polls_{year}/ (legacy) as a
set of per-UF `pesquisa_eleitoral_{year}_<UF>.csv` files (the `_BRASIL`
/ `_BR` aggregates are skipped).

Multi-year usage: iterate over YEARS (default [2020, 2024]). Override
via env var: ``YEARS="2020" python -m source.clean.poll``.

Writes (per year):
  build/clean/poll_{year}.parquet — one row per protocol with columns:
    protocol, uf, muni_code_tse, municipality, cargo,
    pollster_cnpj, institute, institute_fantasy,
    date_start, date_end, date_registered, date_disclosed,
    sample_size, value_brl, election_code,
    st_pesquisa_propria (where present in source schema).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(os.environ["BASE_DIR"])
DATA_DIR = Path(os.environ["DATA_DIR"])
BUILD_DIR = BASE_DIR / "build"
BUILD_CLEAN_DIR = BUILD_DIR / "clean"

# Year list: override via env var YEARS="2020,2024" or edit here.
YEARS = [int(y) for y in os.environ.get("YEARS", "2020,2024").split(",")]

# TSE registry columns we keep (output name in value position). Some
# columns may be absent in older schemas — we keep what's available
# and emit pd.NA elsewhere.
COLUMN_MAP = {
    "NR_PROTOCOLO_REGISTRO": "protocol",
    "DS_CARGO":              "cargo",
    "SG_UF":                 "uf",
    "NM_UE":                 "municipality",
    "SG_UE":                 "muni_code_tse",
    "NR_CNPJ_EMPRESA":       "pollster_cnpj",
    "NM_EMPRESA":            "institute",
    "NM_EMPRESA_FANTASIA":   "institute_fantasy",
    "DT_INICIO_PESQUISA":    "date_start",
    "DT_FIM_PESQUISA":       "date_end",
    "DT_REGISTRO":           "date_registered",
    "DT_DIVULGACAO":         "date_disclosed",
    "QT_ENTREVISTADO":       "sample_size",
    "VR_PESQUISA":           "value_brl",
    "CD_ELEICAO":            "election_code",
    "ST_PESQUISA_PROPRIA":   "st_pesquisa_propria",
}

DATE_COLS    = ["date_start", "date_end", "date_registered", "date_disclosed"]
INT_COLS     = ["sample_size"]
FLOAT_COLS   = ["value_brl"]


def find_registry_dir(year: int) -> Path:
    """Locate the per-year TSE poll registry directory.

    Search order:
      1. DATA_DIR/TSE/{year}/pesquisa_eleitoral/ (canonical server layout)
      2. build/scrape/tse_polls_{year}/ (legacy / symlink)
    """
    candidates = [
        DATA_DIR / "TSE" / str(year) / "pesquisa_eleitoral",
        BUILD_DIR / "scrape" / f"tse_polls_{year}",
    ]
    for d in candidates:
        if d.exists() and any(d.glob("pesquisa_eleitoral_*.csv")):
            return d
    sys.exit(
        f"No registry CSVs found for {year}. Searched:\n"
        + "\n".join(f"  {d}" for d in candidates)
    )


def load_year(year: int) -> pd.DataFrame:
    """Concat per-UF registry CSVs, filter to mayoral, dedupe by protocol."""
    src_dir = find_registry_dir(year)
    csvs = sorted(src_dir.glob(f"pesquisa_eleitoral_{year}_*.csv"))
    csvs = [c for c in csvs if c.stem not in {
        f"pesquisa_eleitoral_{year}_BRASIL",
        f"pesquisa_eleitoral_{year}_BR",
    }]
    if not csvs:
        sys.exit(f"No per-UF registry CSVs in {src_dir}.")

    dfs = []
    for c in csvs:
        df = pd.read_csv(
            c, sep=";", encoding="latin-1", low_memory=False,
            dtype={"NR_CNPJ_EMPRESA": str},
        )
        dfs.append(df)
    raw = pd.concat(dfs, ignore_index=True)
    return raw


def normalize(raw: pd.DataFrame) -> pd.DataFrame:
    """Filter to mayoral polls, rename + type-coerce, dedupe by protocol."""
    df = raw[raw["DS_CARGO"].str.contains("Prefeito", na=False, case=False)].copy()

    # Keep only the columns we map; missing optional columns become NA.
    present = [c for c in COLUMN_MAP if c in df.columns]
    missing = [c for c in COLUMN_MAP if c not in df.columns]
    out = df[present].rename(columns={c: COLUMN_MAP[c] for c in present}).copy()
    for c in missing:
        out[COLUMN_MAP[c]] = pd.NA

    out["pollster_cnpj"] = (
        out["pollster_cnpj"].astype(str).str.replace(r"\D", "", regex=True)
    )
    for c in DATE_COLS:
        out[c] = pd.to_datetime(out[c], errors="coerce")
    for c in INT_COLS:
        out[c] = pd.to_numeric(out[c], errors="coerce").astype("Int64")
    for c in FLOAT_COLS:
        out[c] = pd.to_numeric(
            out[c].astype(str).str.replace(",", ".", regex=False),
            errors="coerce",
        )

    out = out.drop_duplicates("protocol")
    # Stable column order — the order in COLUMN_MAP.
    return out[[COLUMN_MAP[k] for k in COLUMN_MAP]]


def clean_year(year: int) -> None:
    print(f"\n{'=' * 72}")
    print(f"YEAR {year}")
    print(f"{'=' * 72}")
    raw = load_year(year)
    print(f"Loaded {len(raw):,} raw registry rows.")

    poll = normalize(raw)
    print(f"Filtered to mayoral: {len(poll):,} unique protocols "
          f"({poll['uf'].nunique()} UFs, "
          f"{poll['institute'].nunique()} institutes).")
    print(f"Date span: {poll['date_end'].min()} → {poll['date_end'].max()}")

    BUILD_CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    out_path = BUILD_CLEAN_DIR / f"poll_{year}.parquet"
    poll.to_parquet(out_path, index=False)
    print(f"Wrote {out_path}")


def main():
    for year in YEARS:
        clean_year(year)


if __name__ == "__main__":
    main()
