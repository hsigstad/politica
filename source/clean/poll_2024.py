"""Clean & enrich 2024 poll extractions: LLM-extracted vote intentions
joined with TSE registration metadata.

Moved into pipelines/politica 2026-05-28 from
projects/REDACTED-PROJECT/source/clean/ so the cleaned poll table can
be workspace-wide infrastructure rather than legacy-pilot-private.

Reads:
  - build/llm/poll_relatorio_2024.parquet     LLM extractions (long format,
                                              one row per candidate-scenario)
  - path.tse_polls_2024_dir/pesquisa_eleitoral_2024_*.csv
                                              TSE registration metadata
                                              (one row per registered poll).
                                              Currently build/scrape/tse_polls_2024/
                                              (see path.py for migration plan).

Writes:
  - build/clean/poll_2024.parquet             Long-format poll table:
                                              one row per (protocol, scenario_type,
                                              candidate_name) with metadata joined.

The join key is NR_PROTOCOLO_REGISTRO (TSE protocol).  All metadata fields
(institute, dates, sample size, methodology) come from the TSE CSV — we do
not trust the LLM extraction for these fields, only for the vote intentions
themselves.

Candidate-to-TSE-candidate matching (cand_cpf assignment) is a downstream
concern (projects/REDACTED-PROJECT/source/assemble/poll_2024.py and
DOWNSTREAM_PROJECT downstream) and requires the TSE 2024 candidate registry.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

import path


def load_extractions(year: int) -> pd.DataFrame:
    p = path.build_llm_dir / f"poll_relatorio_{year}.parquet"
    if not p.exists():
        sys.exit(f"Missing {p}. Run source/llm/poll_extract.py --year {year} first.")
    df = pd.read_parquet(p)
    return df


def load_tse_metadata(year: int) -> pd.DataFrame:
    """Concatenate per-UF TSE registration CSVs and filter to mayoral polls."""
    if year == 2024:
        src_dir = path.tse_polls_2024_dir
    else:
        src_dir = path.data_dir / f"tse_polls_{year}"
    csvs = sorted(src_dir.glob(f"pesquisa_eleitoral_{year}_*.csv"))
    csvs = [c for c in csvs if c.stem not in {f"pesquisa_eleitoral_{year}_BRASIL",
                                              f"pesquisa_eleitoral_{year}_BR"}]
    if not csvs:
        sys.exit(f"No TSE poll CSVs in {src_dir}.")
    dfs = []
    for c in csvs:
        dfs.append(pd.read_csv(c, sep=";", encoding="latin-1", low_memory=False))
    meta = pd.concat(dfs, ignore_index=True)
    # Filter to polls covering mayoral races (DS_CARGO is comma-separated; substring match)
    meta = meta[meta["DS_CARGO"].str.contains("Prefeito", na=False, case=False)].copy()
    return meta


def normalize_metadata(meta: pd.DataFrame) -> pd.DataFrame:
    """Rename + type-coerce TSE registration fields into our schema."""
    keep = {
        "NR_PROTOCOLO_REGISTRO": "protocol",
        "NM_EMPRESA":            "institute",
        "NM_EMPRESA_FANTASIA":   "institute_fantasy",
        "DT_INICIO_PESQUISA":    "date_start",
        "DT_FIM_PESQUISA":       "date_end",
        "QT_ENTREVISTADO":       "sample_size",
        "SG_UF":                 "uf",
        "NM_UE":                 "municipality",
        "SG_UE":                 "muni_code_tse",
        "DT_REGISTRO":           "date_registered",
        "VR_PESQUISA":           "value_brl",
        "CD_ELEICAO":            "election_code",
    }
    # DT_DIVULGACAO exists in 2024 only
    if "DT_DIVULGACAO" in meta.columns:
        keep["DT_DIVULGACAO"] = "date_disclosed"
    out = meta[list(keep.keys())].rename(columns=keep).copy()
    for c in ["date_start", "date_end", "date_registered"] + (
        ["date_disclosed"] if "date_disclosed" in out.columns else []
    ):
        out[c] = pd.to_datetime(out[c], errors="coerce")
    out["sample_size"] = pd.to_numeric(out["sample_size"], errors="coerce").astype("Int64")
    # VR_PESQUISA uses comma decimal separator (e.g. "4600,00")
    out["value_brl"] = (
        out["value_brl"].astype(str).str.replace(",", ".", regex=False)
    )
    out["value_brl"] = pd.to_numeric(out["value_brl"], errors="coerce")
    # A given protocol can appear in multiple per-UF CSV rows (e.g. polls covering
    # multiple races) — but for Prefeito-only filtered subset it should be 1 row.
    out = out.drop_duplicates("protocol")
    return out


def main():
    year = 2024  # Only 2024 has accessible relatórios (see docs/notes/poll_data_expansion.md)
    ext = load_extractions(year)
    print(f"LLM extractions: {len(ext):,} rows from {ext['protocol'].nunique()} protocols")
    meta = normalize_metadata(load_tse_metadata(year))
    print(f"TSE mayoral registrations: {len(meta):,}")

    # Join (left: extractions; meta is the lookup)
    merged = ext.merge(meta, on="protocol", how="left", validate="many_to_one")
    n_missing = merged["institute"].isna().sum()
    if n_missing:
        protos_missing = merged.loc[merged["institute"].isna(), "protocol"].unique()
        print(f"WARN: {n_missing} extraction rows have no TSE metadata match "
              f"({len(protos_missing)} unique protocols). First 5: "
              f"{list(protos_missing[:5])}")

    out_dir = path.build_clean_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "poll_2024.parquet"
    merged.to_parquet(out_path, index=False)
    print(f"\nWrote {len(merged):,} rows → {out_path}")
    print(f"\ncolumn dtypes:")
    for c in merged.columns:
        print(f"  {c}: {merged[c].dtype}")
    print(f"\nscenario distribution:")
    print(merged["scenario_type"].value_counts().to_string())


if __name__ == "__main__":
    main()
