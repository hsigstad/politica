"""Match poll-extracted candidates to TSE 2024 candidate registry.

The LLM extraction (source/llm/poll_extract.py) returns candidate
NAMES as they appear on poll relatórios — usually nicknames or first
names ("FRANKLIN", "CAPITÃ LUCIMARA") rather than full legal names.
Downstream analyses (e.g. DOWNSTREAM_PROJECT [an] — REDACTED
effects on 2024 polls) need to link each polled candidate to a
specific TSE registry row to recover cpf, party (when poll doesn't
give it), and votes.

This step joins build/clean/poll_2024.parquet to candidato.csv +
politico.csv on (muni_code, fuzzy candidate-name match within the muni).
The fuzzy match exploits the typical structure: 3-8 candidates per
muni, each with a distinctive name token. Strategy:

  score 3  poll_name substring of full name        (most reliable)
  score 2  ≥2 poll tokens are tokens of full name  (e.g. ALEXANDRE TONETTI)
  score 1  single poll token in full name          (e.g. CAPITÃ LUCIMARA → LUCIMARA)
           or last token of poll_name in full name

Aggregate rows ("Branco/Nulo", "Não sabe", etc.) and second-round
simulations are passed through unmatched.

Reads:
  - build/clean/poll_2024.parquet
  - build/clean/candidato.csv  (year=2024, office=PREFEITO universe)
  - build/clean/politico.csv   (politico_id → name lookup)
  - build/scrape/tse_polls_2024/pesquisa_eleitoral_2024_*.csv
      (NR_PROTOCOLO_REGISTRO → SG_UE muni code; the cleaned poll
      parquet drops SG_UE in 2024 layout; re-load here to be safe).

Writes:
  - build/clean/poll_2024__candmatch.parquet
      One row per (protocol, scenario_type, candidate_name) carrying
      cand_cpf, cand_politico (full TSE-registry name), cand_politico_id,
      cand_party (registry party — may differ from poll-reported party),
      cand_votes (TSE-reported actual vote count at the election),
      match_score, match_method, n_match_candidates (>1 = ambiguous).
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd

import path


YEAR = 2024
OFFICE = "PREFEITO"

# Candidate-NAME rows we deliberately skip (no real candidate to match).
# Covers:
#   - aggregate non-candidate rows in vote-intention scenarios
#     (Branco/Nulo/Nenhum/Não sabe/Indeciso/Outros/Não atingiram 1%)
#   - government-evaluation scenarios that get mixed into the parquet
#     (Aprova/Desaprova/Regular/Bom/Ruim/Ótimo/Péssimo) — the LLM
#     occasionally tags those as scenario_type=outro but the candidates
#     column gets the evaluation labels
#   - rejection-poll synonyms ("Poderia votar em todos", "Rejeita nenhum")
#   - "NS/NR" survey shorthand
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


def load_registry() -> pd.DataFrame:
    """2024 PREFEITO candidates, joined with politico for full names."""
    cand = pd.read_csv(
        path.build_clean_dir / "candidato.csv",
        usecols=[
            "cpf", "politico_id", "party", "year", "municipio_id",
            "office", "estado", "votes", "round", "electeddummy",
        ],
        dtype={"party": "string", "office": "string", "estado": "string"},
        low_memory=False,
    )
    cand = cand.query(f"year == {YEAR} and office == '{OFFICE}'").copy()
    cand["muni_code"] = pd.to_numeric(cand["municipio_id"], errors="coerce").astype("Int64")
    # round 1 only (round 2 would be the same person again).
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

    pool is candidato rows for ONE muni.
    """
    if not isinstance(poll_name, str) or AGGREGATE_RE.search(poll_name):
        return None
    name_n = _norm(poll_name)
    if not name_n or pool.empty:
        return None
    poll_tokens = set(name_n.split())

    best = None  # (score, idx)
    n_matches = 0
    for _, r in pool.iterrows():
        full = r["politico_norm"]
        if not full:
            continue
        full_tokens = set(full.split())
        score = 0
        method = None
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


def main():
    poll_path = path.build_clean_dir / "poll_2024.parquet"
    if not poll_path.exists():
        sys.exit(f"Missing {poll_path}. Run source/clean/poll_2024.py first.")
    polls = pd.read_parquet(poll_path)
    print(f"poll rows: {len(polls):,} from {polls['protocol'].nunique()} protocols")

    cand = load_registry()
    print(f"{YEAR} {OFFICE} registry: {len(cand):,} candidates, "
          f"{cand['cpf'].notna().sum():,} with CPF, "
          f"{cand['muni_code'].nunique():,} unique munis")

    proto_to_muni = load_protocol_to_muni()
    polls["muni_code"] = (
        polls["protocol"].map(proto_to_muni).astype("Int64")
    )
    n_no_muni = polls["muni_code"].isna().sum()
    if n_no_muni:
        print(f"  WARN: {n_no_muni:,} poll rows have no muni_code lookup "
              f"(protocols absent from registration CSVs)")

    # Match each poll candidate within its muni's pool. Build the match
    # one muni at a time to keep the inner loop on a small pool.
    out = polls.copy()
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

    out_path = path.build_clean_dir / "poll_2024__candmatch.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_path, index=False)

    n_poll_rows = len(out)
    n_aggregate = out["candidate_name"].fillna("").str.match(AGGREGATE_RE).sum()
    n_matchable = n_poll_rows - n_aggregate

    print(f"\nWrote {len(out):,} rows → {out_path}")
    print(f"  matched: {n_matched:,} / {n_matchable:,} non-aggregate rows "
          f"({n_matched / max(n_matchable,1) * 100:.1f}%)")
    print(f"  with cpf: {out['cand_cpf'].notna().sum():,} "
          f"({out['cand_cpf'].notna().sum() / max(n_matched,1) * 100:.1f}% of matched)")
    print()
    print("Match score distribution:")
    print(out["match_score"].value_counts(dropna=False).to_string())
    print()
    print("Match method (top 10):")
    print(out["match_method"].value_counts(dropna=False).head(10).to_string())


if __name__ == "__main__":
    main()
