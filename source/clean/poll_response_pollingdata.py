"""Tidy the scraped pollingdata.com.br per-election poll archive into one table.

INTENT
    Concatenate the per-election parquets written by
    source/scrape/pollingdata_acervo.py into a single long poll-response table:
    one row per (election, poll, scenario, candidate) with the candidate's vote
    intention. This is the vote-intention time series for state/federal races,
    consumed downstream (joined to the candidate registry for a person id and to
    campaign-finance data by date).

REASONING
    - Faithful long format, mirroring the other poll_response_* tables: aggregate
      rows ("Não Válido") are kept and flagged (is_aggregate) rather than dropped,
      so a share-on-valid can be recomputed downstream.
    - poll_date is the poll's reference date; protocolo is the TSE registration
      number (e.g. BR-05339/2022) and is the join key to the TSE registry for
      sponsor / methodology. institute is normalised (stripped/upper) alongside
      the raw string.

ASSUMES
    - build/scrape/pollingdata_acervo/*.parquet exist (run the scraper first).

Usage:
    python source/clean/poll_response_pollingdata.py
"""
from __future__ import annotations

import pandas as pd

import path

SRC_DIR = path.pollingdata_acervo_dir
OUT = path.build_clean_dir / "poll_response_pollingdata.parquet"

AGGREGATE_LABELS = {"NAO VALIDO", "NÃO VÁLIDO", "NAO VALIDOS", "OUTROS", "BRANCO", "NULO"}


def main() -> None:
    files = sorted(p for p in SRC_DIR.glob("*.parquet"))
    if not files:
        raise SystemExit(f"no scraped parquets in {SRC_DIR} — run the scraper first")
    df = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
    print(f"read {len(files)} elections → {len(df):,} rows")

    df["poll_date"] = pd.to_datetime(df["poll_date"], errors="coerce")
    df["pct"] = pd.to_numeric(df["pct"], errors="coerce")
    df["sample_size"] = pd.to_numeric(df["sample_size"], errors="coerce")
    df["institute"] = df["institute_raw"].astype("string").str.strip().str.upper()
    df["turno"] = df["turno"].astype("string").str.extract(r"([12])", expand=False)
    df["is_aggregate"] = df["candidate"].astype("string").str.strip().str.upper().isin(AGGREGATE_LABELS)

    # share among "real" (non-aggregate) candidates within a poll×scenario
    key = ["url", "protocolo", "cenario"]
    real = df.loc[~df["is_aggregate"]].groupby(key, dropna=False)["pct"].sum().rename("sum_real_pct")
    df = df.merge(real.reset_index(), on=key, how="left", validate="m:1")
    df["pct_on_real"] = pd.NA
    m = ~df["is_aggregate"]
    df.loc[m, "pct_on_real"] = df.loc[m, "pct"] / df.loc[m, "sum_real_pct"] * 100

    cols = ["year", "office", "uf", "turno", "protocolo", "poll_date", "institute",
            "institute_raw", "mode", "sample_size", "cenario", "candidate", "party",
            "pct", "is_aggregate", "sum_real_pct", "pct_on_real", "cargo_raw", "url"]
    df = df[cols].sort_values(["year", "office", "uf", "poll_date", "protocolo"]).reset_index(drop=True)

    path.build_clean_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    print(f"polls: {df['protocolo'].nunique():,} | elections: {df['url'].nunique():,} | "
          f"institutes: {df['institute'].nunique():,}")
    print(f"by office × year:\n{df.drop_duplicates(['url']).groupby(['office','year']).size().to_string()}")
    print(f"Wrote → {OUT.relative_to(path.PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
