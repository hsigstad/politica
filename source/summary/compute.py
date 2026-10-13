# INTENT: compute the per-dataset summary JSON the portal renders — row/col
# counts, per-column dtype + null %, top-20 categorical value-counts, per-year
# temporal histograms, a grain (uniqueness) check, and a masked 50-row sample.
# REASONING: ported from ficha's parquet-only compute, with three politica
# additions: (1) reads CSV *or* parquet (branched on path suffix) — politica's
# core tables are CSV; (2) mask_columns redaction of individual CPFs / titulos,
# because politica is a PUBLIC repo; (3) sample-cell truncation, so the full
# proposta_governo manifesto text doesn't blow up the cache JSON.
# ASSUMES: DatasetConfig carries path/categorical/temporal/key/mask columns;
# temporal aggregates are computed from the raw column BEFORE masking (a
# birth-year histogram is not PII; a birthdate in a sample row is).
from __future__ import annotations

import re
from typing import Any

import pandas as pd

from .config import DatasetConfig

SAMPLE_ROWS = 50
SAMPLE_SEED = 42
TOP_N = 20
CELL_MAX = 200          # truncate every sample/example cell to this many chars

# CPF printed as ###.###.###-## — redact anywhere it appears in a free cell.
_CPF_FMT = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")

# String-encoded binaries: (allowed non-NA values, the label treated as 1).
BINARY_STRING_PAIRS: list[tuple[set[str], str]] = [
    ({"S", "N"}, "S"),
    ({"Y", "N"}, "Y"),
    ({"True", "False"}, "True"),
    ({"true", "false"}, "true"),
    ({"t", "f"}, "t"),
    ({"sim", "nao"}, "sim"),
]


# ── loading ──────────────────────────────────────────────────────────────────
def _read_frame(config: DatasetConfig) -> pd.DataFrame:
    """Read the dataset into a DataFrame, branching on file suffix."""
    path = config.path
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


# ── masking ──────────────────────────────────────────────────────────────────
def _mask_cell(text: str) -> str:
    """Redact CPF-shaped substrings inside an arbitrary cell value."""
    if not text:
        return text
    return _CPF_FMT.sub("[CPF]", text)


def _truncate(text: str) -> str:
    if len(text) > CELL_MAX:
        return text[: CELL_MAX - 1].rstrip() + "…"
    return text


# ── grain check ──────────────────────────────────────────────────────────────
def verify_grain(df: pd.DataFrame, key_columns: list[str] | None) -> dict | None:
    """Check that `key_columns` is a unique, non-null key on `df`."""
    if not key_columns:
        return None
    cols = list(key_columns)
    missing = [c for c in cols if c not in df.columns]
    if missing:
        return {"key_columns": cols, "error": f"columns not in dataframe: {missing}"}
    keys = df[cols]
    n_rows = int(len(df))
    n_null_keys = int(keys.isna().any(axis=1).sum())
    n_unique_keys = int(keys.drop_duplicates().shape[0])
    n_duplicate_rows = n_rows - n_unique_keys
    return {
        "key_columns": cols,
        "n_rows": n_rows,
        "n_unique_keys": n_unique_keys,
        "n_duplicate_rows": n_duplicate_rows,
        "n_null_keys": n_null_keys,
        "is_unique": n_duplicate_rows == 0 and n_null_keys == 0,
    }


# ── per-column helpers ───────────────────────────────────────────────────────
def example_value(s: pd.Series, mask_whole: bool, seed: int = SAMPLE_SEED) -> str:
    """A sampled non-null value, masked + truncated for display."""
    if mask_whole:
        return "[redacted]"
    non_na = s.dropna()
    if non_na.empty:
        return "<all NA>"
    v = non_na.sample(n=1, random_state=seed).iloc[0]
    return _truncate(_mask_cell(str(v)))


def detect_binary(s: pd.Series) -> dict | None:
    """If `s` is binary (bool / {0,1} / {S,N}-style), return its share; else None."""
    if len(s) == 0:
        return None
    na_pct = round(s.isna().mean() * 100, 1)
    non_na = s.dropna()
    if non_na.empty:
        return None
    if pd.api.types.is_bool_dtype(s):
        return {"mean": round(float(non_na.astype(int).mean()), 4),
                "na_pct": na_pct, "true_label": "True"}
    if pd.api.types.is_integer_dtype(s):
        unique = set(non_na.unique().tolist())
        if unique and unique.issubset({0, 1}):
            return {"mean": round(float(non_na.astype(int).mean()), 4),
                    "na_pct": na_pct, "true_label": "1"}
        return None
    if pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s):
        unique = set(non_na.astype(str).unique().tolist())
        for pair, pos in BINARY_STRING_PAIRS:
            if unique and unique.issubset(pair):
                return {"mean": round(float((non_na.astype(str) == pos).mean()), 4),
                        "na_pct": na_pct, "true_label": pos}
    return None


def _temporal_block(series: pd.Series) -> dict | None:
    """Per-year counts for a year-like or date-like column."""
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    in_range = numeric.between(1900, 2100)
    if not numeric.empty and in_range.mean() > 0.99:
        years = numeric[in_range].astype(int).value_counts().sort_index()
        return {
            "min": str(int(years.index.min())),
            "max": str(int(years.index.max())),
            "by_year": {"labels": [int(y) for y in years.index],
                        "values": [int(v) for v in years.values]},
        }
    dt = pd.to_datetime(series, errors="coerce").dropna()
    if dt.empty:
        return None
    years = dt.dt.year.value_counts().sort_index()
    return {
        "min": str(dt.min().date()), "max": str(dt.max().date()),
        "by_year": {"labels": [int(y) for y in years.index],
                    "values": [int(v) for v in years.values]},
    }


# ── driver ───────────────────────────────────────────────────────────────────
def compute_stats(config: DatasetConfig) -> dict[str, Any]:
    path = config.path
    file_size = path.stat().st_size
    df = _read_frame(config)
    nrows, ncols = df.shape
    mask_whole = set(config.mask_columns)

    columns = [{
        "name": c,
        "dtype": str(df[c].dtype),
        "null_count": int(df[c].isna().sum()),
        "null_pct": round(df[c].isna().mean() * 100, 1) if nrows else 0.0,
        "example": example_value(df[c], c in mask_whole),
    } for c in df.columns]

    # Binary columns auto-detected (excluding masked columns); charted together.
    binary: dict[str, dict] = {}
    for c in df.columns:
        if c in mask_whole:
            continue
        b = detect_binary(df[c])
        if b is not None:
            binary[c] = b

    categorical: dict[str, dict] = {}
    for col in config.categorical_columns:
        if col not in df.columns or col in binary or col in mask_whole:
            continue
        vc = df[col].astype("object").where(df[col].notna(), "<NA>") \
                    .value_counts().head(TOP_N)
        categorical[col] = {
            "labels": [str(x) for x in vc.index.tolist()],
            "values": [int(v) for v in vc.values.tolist()],
        }

    # Temporal computed from the RAW column (aggregate, not PII) even when the
    # column is masked in the sample.
    temporal: dict[str, dict] = {}
    for col in config.temporal_columns:
        if col not in df.columns:
            continue
        block = _temporal_block(df[col])
        if block is not None:
            temporal[col] = block

    n_sample = min(SAMPLE_ROWS, nrows)
    sample_df = df.sample(n=n_sample, random_state=SAMPLE_SEED) if nrows else df
    sample_rows: list[list[str]] = []
    for _, row in sample_df.iterrows():
        cells = []
        for col in df.columns:
            if col in mask_whole:
                cells.append("" if pd.isna(row[col]) else "[redacted]")
            elif pd.isna(row[col]):
                cells.append("")
            else:
                cells.append(_truncate(_mask_cell(str(row[col]))))
        sample_rows.append(cells)

    return {
        "id": config.id,
        "name": config.name,
        "description": config.description,
        "grain": config.grain,
        "notes": config.source_notes,
        "category": config.category,
        "layer": config.layer,
        "source_script": config.source_script,
        "file_size": file_size,
        "row_count": nrows,
        "col_count": ncols,
        "columns": columns,
        "binary": binary,
        "categorical": categorical,
        "temporal": temporal,
        "sample_columns": df.columns.tolist(),
        "sample": sample_rows,
        "grain_check": verify_grain(df, config.key_columns),
        "pseudocode": config.pseudocode,
    }
