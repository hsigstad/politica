"""Clean & enrich 2024 poll extractions: LLM-extracted vote intentions
joined with TSE registration metadata and matched to TSE candidate registry.

Moved into pipelines/politica 2026-05-28 from
projects/REDACTED-PROJECT/source/clean/ so the cleaned poll table can
be workspace-wide infrastructure rather than legacy-pilot-private.

Candidate matching (formerly a separate poll_2024__candmatch.py step)
was folded in on 2026-06-02 so that the single output parquet carries
politico_id, cpf, party, votes, and match quality columns.

Reads:
  - build/llm/poll_relatorio_2024.parquet     LLM extractions (long format,
                                              one row per candidate-scenario)
  - path.tse_polls_2024_dir/pesquisa_eleitoral_2024_*.csv
                                              TSE registration metadata
                                              (one row per registered poll).
  - build/clean/candidato.csv  (year=2024, office=PREFEITO universe)
  - build/clean/politico.csv   (politico_id → name lookup)

Writes:
  - build/clean/poll_2024.parquet             Long-format poll table:
                                              one row per (protocol, scenario_type,
                                              candidate_name) with metadata and
                                              candidate-registry match columns.

The join key is NR_PROTOCOLO_REGISTRO (TSE protocol).  All metadata fields
(institute, dates, sample size, methodology) come from the TSE CSV — we do
not trust the LLM extraction for these fields, only for the vote intentions
themselves.

Candidate matching uses a four-level scoring ladder against the TSE 2024
PREFEITO registry within each municipality:

  score 4  nome_urna match (ballot name — highest confidence)
  score 3  poll_name is a substring of the full legal name
  score 2  ≥2 poll tokens shared with full legal name
  score 1  single poll token shared with full legal name

Aggregate rows ("Branco/Nulo", "Não sabe", etc.) are passed through
unmatched.
"""
from __future__ import annotations

import re
import sys
import unicodedata

import pandas as pd

import path


YEAR = 2024
OFFICE = "PREFEITO"

# Candidate-NAME rows we deliberately skip (no real candidate to match).
AGGREGATE_RE = re.compile(
    r"(BRANC|NULO|NENHUM|NAO SAB|NAO RESPOND|NAO OPIN|INDECISO|"
    r"OUTROS|REJEITA NENHUM|NSNR|EM BRANC|NS NR|NAO SEI|"
    r"NAO ATINGIRAM|PODERIA VOTAR EM TODOS|TODOS OS CANDIDATOS|"
    r"APROVA|DESAPROVA|REGULAR|^BOM|^RUIM|OTIMO|PESSIMO|^MAU|^MA$)",
    re.IGNORECASE,
)


def _norm(s) -> str:
    """Uppercase, ASCII-fold, drop punctuation, collapse whitespace."""
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^A-Za-z0-9 ]", " ", s).upper().strip()
    s = re.sub(r"\s+", " ", s)
    return s


# ── Stage 1: LLM extractions + TSE metadata ─────────────────────────


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
    if "DT_DIVULGACAO" in meta.columns:
        keep["DT_DIVULGACAO"] = "date_disclosed"
    out = meta[list(keep.keys())].rename(columns=keep).copy()
    for c in ["date_start", "date_end", "date_registered"] + (
        ["date_disclosed"] if "date_disclosed" in out.columns else []
    ):
        out[c] = pd.to_datetime(out[c], errors="coerce")
    out["sample_size"] = pd.to_numeric(out["sample_size"], errors="coerce").astype("Int64")
    out["value_brl"] = (
        out["value_brl"].astype(str).str.replace(",", ".", regex=False)
    )
    out["value_brl"] = pd.to_numeric(out["value_brl"], errors="coerce")
    out = out.drop_duplicates("protocol")
    return out


# ── Stage 2: candidate matching ──────────────────────────────────────


def load_registry() -> pd.DataFrame:
    """2024 PREFEITO candidates, joined with politico for full names."""
    cand_path = path.build_clean_dir / "candidato.csv"
    header_cols = pd.read_csv(cand_path, nrows=0).columns.tolist()
    base_cols = [
        "cpf", "politico_id", "party", "year", "municipio_id",
        "office", "estado", "votes", "round", "electeddummy",
    ]
    has_urna = "nome_urna" in header_cols
    use_cols = base_cols + (["nome_urna"] if has_urna else [])
    cand = pd.read_csv(
        cand_path,
        usecols=use_cols,
        dtype={"party": "string", "office": "string", "estado": "string"},
        low_memory=False,
    )
    cand = cand.query(f"year == {YEAR} and office == '{OFFICE}'").copy()
    cand["muni_code"] = pd.to_numeric(cand["municipio_id"], errors="coerce").astype("Int64")
    cand["round"] = pd.to_numeric(cand["round"], errors="coerce").astype("Int64")
    cand = cand.loc[cand["round"].isin([1, pd.NA])].copy()

    pol = pd.read_csv(
        path.build_clean_dir / "politico.csv",
        usecols=["politico_id", "politico"],
        dtype={"politico": "string"},
        low_memory=False,
    )
    cand = cand.merge(pol, on="politico_id", how="left")
    cand["politico_norm"] = cand["politico"].fillna("").map(_norm)
    if has_urna:
        cand["nome_urna_norm"] = cand["nome_urna"].fillna("").map(_norm)
    else:
        cand["nome_urna_norm"] = ""
    return cand


def load_protocol_to_muni() -> dict:
    """Map NR_PROTOCOLO_REGISTRO → SG_UE muni code from the polls CSVs."""
    src_dir = path.tse_polls_2024_dir
    csvs = sorted(src_dir.glob(f"pesquisa_eleitoral_{YEAR}_*.csv"))
    csvs = [
        c for c in csvs
        if c.stem not in {f"pesquisa_eleitoral_{YEAR}_BRASIL",
                          f"pesquisa_eleitoral_{YEAR}_BR"}
    ]
    if not csvs:
        sys.exit(f"No polls registration CSVs in {src_dir}")
    dfs = []
    for c in csvs:
        dfs.append(
            pd.read_csv(c, sep=";", encoding="latin-1", low_memory=False,
                        usecols=["NR_PROTOCOLO_REGISTRO", "SG_UE", "DS_CARGO"],
                        dtype=str)
        )
    polls = pd.concat(dfs, ignore_index=True)
    polls = polls[polls["DS_CARGO"].str.contains("Prefeito", na=False)]
    polls = polls.drop_duplicates("NR_PROTOCOLO_REGISTRO")
    polls["muni_code"] = pd.to_numeric(polls["SG_UE"], errors="coerce").astype("Int64")
    return dict(zip(polls["NR_PROTOCOLO_REGISTRO"], polls["muni_code"]))


def best_match(poll_name: str, pool: pd.DataFrame) -> tuple | None:
    """Return (cpf, politico, politico_id, party, votes, score, method)
    for the best registry match of poll_name within pool, or None.

    Scoring ladder (high → low):
      4  nome_urna match — poll_name equals or overlaps the ballot name.
      3  poll_name is a substring of the full legal name.
      2  ≥2 poll tokens shared with full legal name.
      1  single poll token shared with full legal name.
    """
    if not isinstance(poll_name, str) or AGGREGATE_RE.search(poll_name):
        return None
    name_n = _norm(poll_name)
    if not name_n or pool.empty:
        return None
    poll_tokens = set(name_n.split())

    best = None
    n_matches = 0
    for _, r in pool.iterrows():
        full = r["politico_norm"]
        urna = r.get("nome_urna_norm", "")
        score = 0
        method = None
        if urna and (name_n == urna or name_n in urna or urna in name_n):
            score = 4
            method = "nome_urna"
        elif full:
            full_tokens = set(full.split())
            if name_n in full:
                score = 3
                method = "substring"
            elif poll_tokens & full_tokens:
                shared = poll_tokens & full_tokens
                score = 2 if len(shared) >= 2 else 1
                method = f"tokens={','.join(sorted(shared))}"
        if score == 0:
            continue
        n_matches += 1
        if best is None or score > best[0]:
            best = (score, r, method)
    if best is None:
        return None
    score, r, method = best
    return (
        r["cpf"], r["politico"], r["politico_id"],
        r["party"], r["votes"],
        score, method, n_matches,
    )


# ── Main ─────────────────────────────────────────────────────────────


def main():
    # Stage 1: LLM extractions + TSE metadata
    ext = load_extractions(YEAR)
    print(f"LLM extractions: {len(ext):,} rows from {ext['protocol'].nunique()} protocols")
    meta = normalize_metadata(load_tse_metadata(YEAR))
    print(f"TSE mayoral registrations: {len(meta):,}")

    merged = ext.merge(meta, on="protocol", how="left", validate="many_to_one")
    n_missing = merged["institute"].isna().sum()
    if n_missing:
        protos_missing = merged.loc[merged["institute"].isna(), "protocol"].unique()
        print(f"WARN: {n_missing} extraction rows have no TSE metadata match "
              f"({len(protos_missing)} unique protocols). First 5: "
              f"{list(protos_missing[:5])}")

    # Stage 2: candidate matching
    cand = load_registry()
    print(f"\n{YEAR} {OFFICE} registry: {len(cand):,} candidates, "
          f"{cand['cpf'].notna().sum():,} with CPF, "
          f"{cand['muni_code'].nunique():,} unique munis")

    proto_to_muni = load_protocol_to_muni()
    merged["muni_code"] = (
        merged["protocol"].map(proto_to_muni).astype("Int64")
    )
    n_no_muni = merged["muni_code"].isna().sum()
    if n_no_muni:
        print(f"  WARN: {n_no_muni:,} rows have no muni_code lookup "
              f"(protocols absent from registration CSVs)")

    out = merged.copy()
    out["cand_cpf"] = pd.array([pd.NA] * len(out), dtype="Float64")
    out["cand_politico"] = pd.array([pd.NA] * len(out), dtype="string")
    out["cand_politico_id"] = pd.array([pd.NA] * len(out), dtype="string")
    out["cand_party"] = pd.array([pd.NA] * len(out), dtype="string")
    out["cand_votes"] = pd.array([pd.NA] * len(out), dtype="Float64")
    out["match_score"] = pd.array([pd.NA] * len(out), dtype="Int64")
    out["match_method"] = pd.array([pd.NA] * len(out), dtype="string")
    out["n_match_candidates"] = pd.array([pd.NA] * len(out), dtype="Int64")

    cand_by_muni = {k: g for k, g in cand.groupby("muni_code")}

    n_matched = 0
    for i, row in out.iterrows():
        muni = row["muni_code"]
        if pd.isna(muni):
            continue
        pool = cand_by_muni.get(muni)
        if pool is None:
            continue
        m = best_match(row["candidate_name"], pool)
        if m is None:
            continue
        (cpf, politico, politico_id, party, votes,
         score, method, n_match) = m
        out.at[i, "cand_cpf"] = cpf
        out.at[i, "cand_politico"] = politico
        out.at[i, "cand_politico_id"] = str(politico_id) if politico_id is not None else pd.NA
        out.at[i, "cand_party"] = party
        out.at[i, "cand_votes"] = votes
        out.at[i, "match_score"] = score
        out.at[i, "match_method"] = method
        out.at[i, "n_match_candidates"] = n_match
        n_matched += 1

    # Write
    out_dir = path.build_clean_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "poll_2024.parquet"
    out.to_parquet(out_path, index=False)

    n_aggregate = out["candidate_name"].fillna("").str.match(AGGREGATE_RE).sum()
    n_matchable = len(out) - n_aggregate

    print(f"\nWrote {len(out):,} rows → {out_path}")
    print(f"  matched: {n_matched:,} / {n_matchable:,} non-aggregate rows "
          f"({n_matched / max(n_matchable, 1) * 100:.1f}%)")
    print(f"  with cpf: {out['cand_cpf'].notna().sum():,} "
          f"({out['cand_cpf'].notna().sum() / max(n_matched, 1) * 100:.1f}% of matched)")
    print(f"\nMatch score distribution:")
    print(out["match_score"].value_counts(dropna=False).to_string())
    print(f"\nMatch method (top 10):")
    print(out["match_method"].value_counts(dropna=False).head(10).to_string())


if __name__ == "__main__":
    main()
