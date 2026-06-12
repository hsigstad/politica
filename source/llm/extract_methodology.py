"""Bulk extract + assemble poll-methodology features.

Pipeline for each of the three tasks (poll_sampling, poll_coverage,
poll_operations):

  1. Apply deterministic short-circuits where applicable (coverage only:
     deferred-complement boilerplate and very-short / empty texts get
     classified without an LLM call).
  2. Dedupe by text_hash within the polls that still need LLM. Pollsters
     reuse boilerplate across their polls — typically a few hundred unique
     pollster × template combinations across the 14k mayor-race polls.
  3. Run the wrapper on one canonical protocol per text_hash (cache
     persists across runs).
  4. Propagate the canonical extraction to all protocols sharing the
     same text.
  5. Assemble all three tasks into one wide parquet, keyed on protocol.

Reads:
  - pipelines/politica/build/scrape/tse_polls_2024/pesquisa_eleitoral_2024_*.csv

Writes:
  - pipelines/politica/build/llm/poll_methodology_2024.parquet (wide)
  - pipelines/politica/build/llm/poll_methodology_2024_summary.json
  - per-task caches at pipelines/politica/build/llm/poll_{task}/ (managed by wrappers)

Run:
  PYTHONPATH=/path/to/llmkit:$PWD/source/llm \\
  BASE_DIR=$PWD \\
    python3 extract_methodology.py --n 200          # 200-poll subset
    python3 extract_methodology.py --all            # full ~14,876 mayor polls
    python3 extract_methodology.py --n 200 --dry-run  # plan only, no LLM
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Callable

import openai
import pandas as pd

from poll_sampling import extract_poll_sampling
from poll_coverage import extract_poll_coverage, MIN_TEXT_CHARS as COV_MIN_CHARS
from poll_operations import extract_poll_operations

BASE_DIR = Path(os.environ["BASE_DIR"])
RAW_DIR = BASE_DIR / "build" / "scrape" / "tse_polls_2024"
OUT_DIR = BASE_DIR / "build" / "llm"
OUT_DIR.mkdir(parents=True, exist_ok=True)

POLL_COLS = [
    "NR_PROTOCOLO_REGISTRO", "SG_UF", "NM_UE", "DS_CARGO",
    "NM_EMPRESA", "NM_EMPRESA_FANTASIA", "NR_CNPJ_EMPRESA",
    "NM_ESTATISTICO_RESP", "CD_CONRE",
    "DT_REGISTRO", "DT_INICIO_PESQUISA", "DT_FIM_PESQUISA", "DT_DIVULGACAO",
    "QT_ENTREVISTADO", "VR_PESQUISA", "ST_PESQUISA_PROPRIA",
    "DS_METODOLOGIA_PESQUISA", "DS_PLANO_AMOSTRAL",
    "DS_SISTEMA_CONTROLE", "DS_DADO_MUNICIPIO",
]


# ── Coverage deterministic short-circuit ────────────────────────────

DEFERRED_PATTERN = re.compile(
    r"complementad|complemento posterior"
    r"|res(olu[cç][aã]o)?\s*(tse)?\s*n[ºo]?\s*23\.?600"
    r"|§\s*7[º°]|paragrafo\s+s[ée]timo"
    r"|art\.?\s*2[º°].{0,80}res",
    flags=re.IGNORECASE,
)


def coverage_bucket(text: str) -> str:
    t = (text or "").strip()
    if not t or t.lower() in {"nan", "none"}:
        return "empty"
    if len(t) < COV_MIN_CHARS:
        return "very_short"
    if DEFERRED_PATTERN.search(t):
        return "deferred_complement"
    return "substantive"


def deterministic_coverage_record(bucket: str, text: str) -> dict:
    """Construct a PollCoverage-shaped dict without an LLM call. Used
    for empty / very_short / deferred_complement polls."""
    if bucket == "deferred_complement":
        return {
            "coverage_class": "deferred_complement",
            "coverage_class_evidence": (text or "")[:300],
            "rural_included": False,
            "rural_excluded_explicitly": False,
            "neighborhoods_listed": [],
            "n_neighborhoods_or_districts": 0,
            "excluded_areas_listed": [],
            "coverage_to_be_complemented": True,
            "coverage_field_substantive": False,
            "extraction_notes": "deterministic: matched deferred-complement regex on DS_DADO_MUNICIPIO",
        }
    return {
        "coverage_class": "not_specified",
        "coverage_class_evidence": (text or "")[:300],
        "rural_included": False,
        "rural_excluded_explicitly": False,
        "neighborhoods_listed": [],
        "n_neighborhoods_or_districts": 0,
        "excluded_areas_listed": [],
        "coverage_to_be_complemented": False,
        "coverage_field_substantive": False,
        "extraction_notes": f"deterministic: DS_DADO_MUNICIPIO bucket={bucket}",
    }


# ── Helpers ─────────────────────────────────────────────────────────

def text_hash(text: str) -> str:
    return hashlib.blake2b((text or "").encode("utf-8"), digest_size=12).hexdigest()


def load_universe() -> pd.DataFrame:
    csvs = sorted(RAW_DIR.glob("pesquisa_eleitoral_2024_*.csv"))
    csvs = [c for c in csvs if c.stem not in
            {"pesquisa_eleitoral_2024_BRASIL", "pesquisa_eleitoral_2024_BR"}]
    dfs = []
    for c in csvs:
        df = pd.read_csv(c, sep=";", encoding="latin-1", low_memory=False, usecols=POLL_COLS)
        dfs.append(df)
    df = pd.concat(dfs, ignore_index=True)
    df = df[df["DS_CARGO"].str.contains("Prefeito", na=False, case=False)].copy()
    df = df.drop_duplicates(subset=["NR_PROTOCOLO_REGISTRO"]).reset_index(drop=True)
    return df


def dedupe_extract(
    df: pd.DataFrame,
    text_fn: Callable[[pd.Series], str],
    extract_fn: Callable[[pd.Series, openai.OpenAI], dict | None],
    client: openai.OpenAI,
    task_name: str,
    dry_run: bool = False,
) -> tuple[pd.Series, int, int]:
    """Hash each row's input text, run extract on the FIRST row per
    text_hash, propagate to siblings. Returns (series_of_dicts,
    n_unique, n_llm_calls)."""
    hashes = df.apply(text_fn, axis=1).apply(text_hash)
    df = df.assign(_hash=hashes)
    unique_protocols = df.drop_duplicates("_hash").reset_index(drop=True)
    print(f"  [{task_name}] {len(df):,} polls → {len(unique_protocols):,} unique texts "
          f"({len(unique_protocols)/max(len(df),1)*100:.1f}%)")
    if dry_run:
        return pd.Series([None] * len(df), index=df.index), len(unique_protocols), 0

    by_hash: dict[str, dict | None] = {}
    n_calls = 0
    t0 = time.time()
    for i, row in unique_protocols.iterrows():
        result = extract_fn(row, client)
        by_hash[row["_hash"]] = result.raw if (result is not None and result.valid) else None
        if result is not None and not result.cached:
            n_calls += 1
        if (i + 1) % 50 == 0 or (i + 1) == len(unique_protocols):
            elapsed = time.time() - t0
            print(f"    {i+1:5,d}/{len(unique_protocols):,}  "
                  f"({n_calls} fresh LLM calls, {elapsed:.0f}s)")
    return df["_hash"].map(by_hash), len(unique_protocols), n_calls


# ── Task adapters ──────────────────────────────────────────────────

def sampling_text(row: pd.Series) -> str:
    return (str(row.get("DS_METODOLOGIA_PESQUISA") or "")
            + "\n\n" + str(row.get("DS_PLANO_AMOSTRAL") or ""))


def sampling_extract(row, client):
    return extract_poll_sampling(
        protocol=str(row["NR_PROTOCOLO_REGISTRO"]),
        uf=str(row["SG_UF"]),
        institute=str(row.get("NM_EMPRESA") or ""),
        ds_metodologia=str(row.get("DS_METODOLOGIA_PESQUISA") or ""),
        ds_plano_amostral=str(row.get("DS_PLANO_AMOSTRAL") or ""),
        client=client,
    )


def coverage_text(row: pd.Series) -> str:
    return str(row.get("DS_DADO_MUNICIPIO") or "")


def coverage_extract(row, client):
    return extract_poll_coverage(
        protocol=str(row["NR_PROTOCOLO_REGISTRO"]),
        municipality=str(row.get("NM_UE") or ""),
        uf=str(row["SG_UF"]),
        ds_dado_municipio=str(row.get("DS_DADO_MUNICIPIO") or ""),
        ds_plano_amostral=str(row.get("DS_PLANO_AMOSTRAL") or ""),
        client=client,
    )


def operations_text(row: pd.Series) -> str:
    return (str(row.get("DS_METODOLOGIA_PESQUISA") or "")
            + "\n\n" + str(row.get("DS_SISTEMA_CONTROLE") or ""))


def operations_extract(row, client):
    return extract_poll_operations(
        protocol=str(row["NR_PROTOCOLO_REGISTRO"]),
        uf=str(row["SG_UF"]),
        institute=str(row.get("NM_EMPRESA") or ""),
        ds_metodologia=str(row.get("DS_METODOLOGIA_PESQUISA") or ""),
        ds_sistema_controle=str(row.get("DS_SISTEMA_CONTROLE") or ""),
        client=client,
    )


# ── Assemble wide row ──────────────────────────────────────────────

def flatten(prefix: str, ext: dict | None, *, missing_marker: str = "missing") -> dict:
    """Flatten an extraction dict into prefixed columns. List / dict
    values are JSON-encoded. Returns {} if extraction is None."""
    if ext is None:
        return {f"{prefix}__extraction_status": missing_marker}
    out = {f"{prefix}__extraction_status": "ok"}
    for k, v in ext.items():
        col = f"{prefix}__{k}"
        if isinstance(v, (list, dict)):
            out[col] = json.dumps(v, ensure_ascii=False)
        else:
            out[col] = v
    return out


# ── Main ─────────────────────────────────────────────────────────────

def main(n: int | None, dry_run: bool, seed: int) -> int:
    print(f"[1/4] Load mayor-race poll registrations")
    df = load_universe()
    print(f"      {len(df):,} mayor polls")
    if n is not None and n < len(df):
        df = df.sample(n=n, random_state=seed).reset_index(drop=True)
        print(f"      subset to {len(df):,} (seed={seed})")

    print(f"[2/4] Apply deterministic coverage short-circuit")
    df["_cov_bucket"] = df["DS_DADO_MUNICIPIO"].apply(coverage_bucket)
    bucket_counts = df["_cov_bucket"].value_counts()
    for b, c in bucket_counts.items():
        print(f"      {b:25s} {c:5,d} ({c/len(df)*100:.1f}%)")

    client = openai.OpenAI() if not dry_run else None

    print(f"[3/4] Extract per task")

    # poll_sampling — full universe via dedupe
    samp_ext, samp_uniq, samp_calls = dedupe_extract(
        df, sampling_text, sampling_extract, client, "sampling", dry_run=dry_run,
    )
    df["_sampling"] = samp_ext.values

    # poll_coverage — only on substantive subset
    cov_mask = df["_cov_bucket"] == "substantive"
    print(f"  [coverage] short-circuit covers {(~cov_mask).sum():,}; LLM on {cov_mask.sum():,}")
    df["_coverage"] = None
    if cov_mask.any():
        cov_sub = df.loc[cov_mask].copy()
        cov_ext_sub, cov_uniq, cov_calls = dedupe_extract(
            cov_sub, coverage_text, coverage_extract, client, "coverage", dry_run=dry_run,
        )
        df.loc[cov_mask, "_coverage"] = cov_ext_sub.values
    else:
        cov_uniq = cov_calls = 0
    # Fill non-substantive with deterministic records
    for idx in df.index[~cov_mask]:
        df.at[idx, "_coverage"] = deterministic_coverage_record(
            df.at[idx, "_cov_bucket"], df.at[idx, "DS_DADO_MUNICIPIO"],
        )

    # poll_operations — full universe via dedupe
    ops_ext, ops_uniq, ops_calls = dedupe_extract(
        df, operations_text, operations_extract, client, "operations", dry_run=dry_run,
    )
    df["_operations"] = ops_ext.values

    print(f"[4/4] Assemble wide parquet")
    rows = []
    for _, row in df.iterrows():
        meta = {
            "protocol": row["NR_PROTOCOLO_REGISTRO"],
            "uf": row["SG_UF"],
            "municipality": row["NM_UE"],
            "institute": row.get("NM_EMPRESA"),
            "institute_fantasy": row.get("NM_EMPRESA_FANTASIA"),
            "cnpj_pollster": row.get("NR_CNPJ_EMPRESA"),
            "statistician": row.get("NM_ESTATISTICO_RESP"),
            "cd_conre": row.get("CD_CONRE"),
            "dt_registro": row.get("DT_REGISTRO"),
            "dt_inicio_pesquisa": row.get("DT_INICIO_PESQUISA"),
            "dt_fim_pesquisa": row.get("DT_FIM_PESQUISA"),
            "dt_divulgacao": row.get("DT_DIVULGACAO"),
            "qt_entrevistado": row.get("QT_ENTREVISTADO"),
            "vr_pesquisa": row.get("VR_PESQUISA"),
            "st_pesquisa_propria": row.get("ST_PESQUISA_PROPRIA"),
            "cov_bucket": row["_cov_bucket"],
        }
        meta.update(flatten("sampling", row["_sampling"]))
        meta.update(flatten("coverage", row["_coverage"]))
        meta.update(flatten("operations", row["_operations"]))
        rows.append(meta)

    out_df = pd.DataFrame(rows)
    out_path = OUT_DIR / "poll_methodology_2024.parquet"
    if n is not None:
        # subset run — write to a different path to avoid clobbering full runs
        out_path = OUT_DIR / f"poll_methodology_2024__subset_n{n}.parquet"
    out_df.to_parquet(out_path, index=False)
    print(f"      wrote {len(out_df):,} rows × {len(out_df.columns)} cols → {out_path}")

    summary = {
        "n_polls": int(len(df)),
        "subset_n": n,
        "dry_run": dry_run,
        "coverage_buckets": bucket_counts.to_dict(),
        "per_task": {
            "sampling": {
                "n_unique_texts": int(samp_uniq),
                "n_fresh_llm_calls": int(samp_calls),
                "n_valid_extractions": int(df["_sampling"].notna().sum()),
            },
            "coverage": {
                "n_unique_texts_substantive": int(cov_uniq),
                "n_fresh_llm_calls_substantive": int(cov_calls),
                "n_deterministic": int((~cov_mask).sum()),
                "n_valid_extractions": int(df["_coverage"].notna().sum()),
            },
            "operations": {
                "n_unique_texts": int(ops_uniq),
                "n_fresh_llm_calls": int(ops_calls),
                "n_valid_extractions": int(df["_operations"].notna().sum()),
            },
        },
    }
    summary_path = out_path.with_suffix("").as_posix() + "_summary.json"
    Path(summary_path).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"      summary → {summary_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=None, help="Subset size; omit for full run.")
    ap.add_argument("--all", action="store_true", help="Run on full mayor-race universe.")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dry-run", action="store_true",
                    help="Plan only — count uniques per task, no LLM calls.")
    args = ap.parse_args()
    n = None if args.all else args.n
    sys.exit(main(n=n, dry_run=args.dry_run, seed=args.seed))
