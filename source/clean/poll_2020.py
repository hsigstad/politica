"""Clean the 2020 mayoral poll long-format export from pollingdata.com.br.

INTENT: produce a long-format 2020 poll table parallel in shape to
`build/clean/poll_2024.parquet`, with aggregate rows ("Nao Validos",
"Outros") preserved and a per-poll `percent_on_real` recomputed on
the real-candidate denominator. Downstream consumers (legacy-pilot's
`source/merge/cand_poll_2020_real_cands.py`) use `percent_on_real`
to apply [an]'s real-cands-only RD outcome symmetrically across
2020 and 2024.

REASONING:
- `polls_prefeito.csv` (sourced by Gui from pollingdata.com.br;
  staged at `build/scrape/pollingdata/polls_prefeito.csv`) is
  already long-format: one row per (Data, Instituto, ibge7_code,
  round, candidate), with aggregate rows present alongside real
  candidates. Years 2012/2016/2020 are pooled; this script filters
  to 2020 and uses `ibge7_code` as the muni key.
- pollingdata's 2020 schema is COARSER than 2024: there are only
  two aggregate-row labels — "Nao Validos" (combined
  Brancos+Nulos+NS/Indecisos) and "Outros" (pollingdata's own
  lumping of small-share candidates the institute reported
  individually). The 2024 8-category schema (has_branc / has_ns /
  has_outros) has no counterpart in 2020, so this script does NOT
  emit schema flags. [an]'s schema-FE robustness leaves 2020 as
  an NA-schema group as before.
- `percent_on_real` recomputes each real-cand row's value as
  `value / sum_of_real_values_in_poll * 100`. Aggregate rows
  ("Nao Validos", "Outros") are excluded from both the numerator
  and the denominator. This is symmetric with the 2024 definition
  used in legacy-pilot's `source/merge/cand_poll_2024_schema.py`.
- A row's `row_type` is one of: `real`, `nao_validos`, `outros`.

ASSUMES:
- `build/scrape/pollingdata/polls_prefeito.csv` has columns
  Data,Instituto,candidate,value,year,round,muni_name_upper,UF,ibge7_code
  (verified against the 2026-06-16 staged copy).
- Real candidates are tagged in `candidate` as "<Name> (<PARTY>)".
- Aggregate rows have `candidate` literally "Nao Validos" or
  "Outros" (verified on the 2020 slice — no other aggregate
  labels surface in the sample).

CAVEAT (documented for [an] consumers): pollingdata-2020's
"Outros" is the AGGREGATOR's lumping of small-share candidates,
not the institute's. So the 2020 `percent_on_real` denominator
excludes those tail candidates that the institute originally
listed individually but pollingdata collapsed. 2024 is not subject
to this asymmetry (the 2024 long parquet preserves every listed
candidate). For mayoral races this is typically minor — the top
2-3 candidates dominate — but worth flagging in any analysis
that pools 2020 and 2024 on `percent_on_real`.

SOURCE: `polls_prefeito.csv` provided by Gui Lambais (coauthor),
exported from pollingdata.com.br. Staged on 2026-06-16 from
EXTERNAL_MIRROR

Writes:
  build/clean/poll_2020.parquet — long format, one row per
    (data_poll, instituto_poll, ibge7_code, round, candidate).
    Columns: data_poll, instituto_poll, ibge7_code, muni_name,
    uf, round, candidate, value, row_type, sum_real_pct,
    percent_on_real.
"""
from __future__ import annotations

import pandas as pd

import path

YEAR = 2020
SRC = path.pollingdata_dir / "polls_prefeito.csv"
OUT = path.build_clean_dir / "poll_2020.parquet"

AGGREGATE_LABELS = {"NAO VALIDOS", "OUTROS"}


def classify_row(candidate: str) -> str:
    """Tag each row as `real`, `nao_validos`, or `outros`."""
    label = candidate.strip().upper()
    if label == "NAO VALIDOS":
        return "nao_validos"
    if label == "OUTROS":
        return "outros"
    return "real"


def main() -> None:
    df = pd.read_csv(SRC, dtype={"ibge7_code": "Int64"})
    df = df.loc[df["year"] == YEAR].copy()
    print(f"polls_prefeito.csv {YEAR}: {len(df):,} rows, "
          f"{df['ibge7_code'].nunique()} unique munis")

    df = df.rename(columns={
        "Data": "data_poll",
        "Instituto": "instituto_poll",
        "muni_name_upper": "muni_name",
        "UF": "uf",
    })
    df["data_poll"] = pd.to_datetime(df["data_poll"])
    df["round"] = df["round"].str.extract(r"([12])", expand=False)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    df["row_type"] = df["candidate"].map(classify_row)
    n_by_type = df["row_type"].value_counts()
    print(f"row_type breakdown:\n{n_by_type.to_string()}")

    poll_key = ["data_poll", "instituto_poll", "ibge7_code", "round"]
    real_sum = (
        df.loc[df["row_type"] == "real"]
          .groupby(poll_key)["value"].sum()
          .rename("sum_real_pct")
          .reset_index()
    )
    df = df.merge(real_sum, on=poll_key, how="left", validate="m:1")

    real_mask = df["row_type"] == "real"
    df["percent_on_real"] = pd.NA
    df.loc[real_mask, "percent_on_real"] = (
        df.loc[real_mask, "value"] / df.loc[real_mask, "sum_real_pct"] * 100
    )

    cols = [
        "data_poll", "instituto_poll", "ibge7_code", "muni_name", "uf",
        "round", "candidate", "value", "row_type",
        "sum_real_pct", "percent_on_real",
    ]
    out = df[cols].sort_values(poll_key + ["row_type", "candidate"])

    path.build_clean_dir.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT, index=False)
    print(f"\nWrote {len(out):,} rows → {OUT}")
    print(f"  unique polls: {out.groupby(poll_key).ngroups:,}")
    print(f"  with percent_on_real: {out['percent_on_real'].notna().sum():,}")


if __name__ == "__main__":
    main()
