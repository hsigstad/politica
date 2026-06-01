"""Join 2024 poll sponsors to mayoral candidates (Routes A + B).

Reads `build/clean/poll_sponsor_2024.parquet` (long sponsor table from
`poll_sponsor_2024.py`) and links each sponsor row to a specific 2024
PREFEITO candidate when one of the three routes applies:

  Route A — sponsor CPF == candidate CPF, within muni.
            Direct join on (sponsor_id == cpf, muni_code_tse == municipio_id).
            ~7% of mayoral-poll sponsor rows are CPF-identified; only the
            subset where the CPF belongs to the muni's PREFEITO candidate
            counts (the rest are treasurers / managers / family — kept
            in the output with sponsor_route=NULL).

  Route B — sponsor CNPJ is a candidate committee (CNPJ name starts with
            "ELEIÇÃO 2024 {NOME COMPLETO} PREFEITO"). The candidate name
            is parsed from the sponsor_name string. Cross-checked by
            looking up the parsed name in candidato.politico for the same
            muni — discrepancies flag committees with non-standard naming
            (~3-5% expected). VICE-PREFEITO committees are deliberately
            excluded (the committee belongs to the running mate, not the
            mayoral candidate; could be added later as a separate flag).

  Route C — party CNPJ → party's PREFEITO in muni (1:1 by the electoral-
            law constraint we lean on for identification). DEFERRED here
            because we don't have a TSE partidos CNPJ table in the
            workspace yet — flagged in todo.md.

The within-candidate FE design is feasible if many candidates appear in
BOTH self-sponsored AND other-sponsored polls in their own race. The
script prints the headline overlap count at the end (per Route A, Route
B, and union).

Reads:
  - build/clean/poll_sponsor_2024.parquet
  - build/clean/candidato.csv  (year=2024, office=PREFEITO universe;
      CPFs zero-padded to 11 to undo legacy float-cast loss)
  - build/clean/politico.csv   (politico_id → name lookup)

Writes:
  - build/clean/poll_sponsor_2024_candidate.parquet
      Same rows as poll_sponsor_2024.parquet plus:
        sponsor_route ∈ {'cpf', 'committee', None}
        sponsor_candidate_cpf       — matched candidate CPF (or None)
        sponsor_candidate_politico_id
        sponsor_candidate_name      — politico.csv name (registry-truth)
        sponsor_candidate_name_parsed — name as parsed from committee
                                        (Route B only)
        sponsor_candidate_party
        sponsor_candidate_votes
        committee_office            — 'PREFEITO' / 'VICE-PREFEITO'
                                       (Route B only)
"""
from __future__ import annotations

import os
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(os.environ["BASE_DIR"])
BUILD_CLEAN = BASE_DIR / "build" / "clean"
SPONSOR_IN = BUILD_CLEAN / "poll_sponsor_2024.parquet"
CANDIDATO_CSV = BUILD_CLEAN / "candidato.csv"
POLITICO_CSV = BUILD_CLEAN / "politico.csv"
OUT = BUILD_CLEAN / "poll_sponsor_2024_candidate.parquet"

# Pattern for candidate-committee names. TSE's standard naming is
# "ELEICAO 2024 {NOME COMPLETO} {PREFEITO|VICE-PREFEITO}" (rendered
# without the ç in the sponsor table). The {NOME} is greedy but the
# trailing role suffix is the anchor — so we capture everything
# between "ELEICAO 2024" and the role.
COMMITTEE_RE = re.compile(
    r"ELEI[CÇ][AÃ]O\s+2024\s+(.+?)\s+(VICE\s*-?\s*PREFEITO|PREFEITO)\s*$",
    re.IGNORECASE,
)


def _norm_name(s: str) -> str:
    """Uppercase, ASCII-fold, drop punctuation, collapse whitespace.
    Used for cross-checking parsed committee names against the politico
    registry."""
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^A-Za-z0-9 ]", " ", s).upper().strip()
    return re.sub(r"\s+", " ", s)


def load_mayoral_candidates() -> pd.DataFrame:
    """2024 PREFEITO candidate panel with CPF, muni, party, votes, and
    politico_id-joined name. CPFs zero-padded to 11; muni_id stripped
    of the spurious '.0' from the year-as-float cast in the clean
    pipeline."""
    c = pd.read_csv(
        CANDIDATO_CSV, dtype=str,
        usecols=[
            "cpf", "year", "office", "municipio_id",
            "votes", "party", "politico_id",
        ],
    )
    c = c[(c["year"] == "2024.0") & (c["office"] == "PREFEITO")].copy()
    c["cpf"] = c["cpf"].fillna("").str.zfill(11)
    c["muni_id"] = c["municipio_id"].str.replace(r"\.0$", "", regex=True)
    p = pd.read_csv(POLITICO_CSV, dtype=str, usecols=["politico_id", "politico"])
    c = c.merge(p, on="politico_id", how="left")
    c["politico_norm"] = c["politico"].map(_norm_name)
    return c.rename(columns={
        "cpf": "cand_cpf",
        "votes": "cand_votes",
        "party": "cand_party",
        "politico_id": "cand_politico_id",
        "politico": "cand_name",
    })[[
        "cand_cpf", "muni_id", "cand_party", "cand_votes",
        "cand_politico_id", "cand_name", "politico_norm",
    ]]


def route_a_cpf(sponsor: pd.DataFrame, cands: pd.DataFrame) -> pd.DataFrame:
    """Match sponsor rows where sponsor_id is a CPF to a PREFEITO
    candidate in the same muni. Returns the matched subset with cand_*
    columns appended; non-matches are not included."""
    s = sponsor[sponsor["id_type"] == "CPF"].copy()
    s["muni_id"] = s["muni_code_tse"].astype("Int64").astype(str)
    j = s.merge(
        cands, left_on=["sponsor_id", "muni_id"], right_on=["cand_cpf", "muni_id"],
        how="inner",
    )
    j["sponsor_route"] = "cpf"
    j["sponsor_candidate_name_parsed"] = pd.NA
    j["committee_office"] = pd.NA
    return j


def route_b_committee(sponsor: pd.DataFrame, cands: pd.DataFrame) -> pd.DataFrame:
    """Parse 'ELEICAO 2024 {NOME} {PREFEITO|VICE-PREFEITO}' from the
    sponsor name. Cross-check the parsed name against candidato in the
    same muni (matching on ASCII-folded uppercase). VICE-PREFEITO rows
    are kept with route=committee and committee_office=VICE-PREFEITO but
    NOT joined to a PREFEITO candidate — the relationship is between
    running mates, not direct sponsorship of the mayoral candidate."""
    s = sponsor[sponsor["id_type"] == "CNPJ"].copy()
    parsed = s["sponsor_name"].fillna("").str.extract(COMMITTEE_RE)
    s["sponsor_candidate_name_parsed"] = parsed[0].str.strip()
    s["committee_office"] = (
        parsed[1].str.upper()
                 .str.replace(r"\s+", "", regex=True)
                 .str.replace("-", "", regex=False)
    )
    s = s[s["sponsor_candidate_name_parsed"].notna()].copy()
    s["parsed_norm"] = s["sponsor_candidate_name_parsed"].map(_norm_name)
    s["muni_id"] = s["muni_code_tse"].astype("Int64").astype(str)

    # PREFEITO committee: cross-check parsed name → candidato in same muni
    prefeito = s[s["committee_office"] == "PREFEITO"].copy()
    j = prefeito.merge(
        cands, left_on=["parsed_norm", "muni_id"],
        right_on=["politico_norm", "muni_id"], how="left",
    )
    j["sponsor_route"] = "committee"

    # VICE-PREFEITO committees: keep tag but no PREFEITO candidate join
    # (sponsorship is by the vice's committee, indirect on the mayoral
    # ticket; downstream can decide whether to use them).
    vice = s[s["committee_office"] == "VICEPREFEITO"].copy()
    for col in ["cand_cpf", "cand_party", "cand_votes",
                "cand_politico_id", "cand_name", "politico_norm"]:
        vice[col] = pd.NA
    vice["sponsor_route"] = "committee"

    return pd.concat([j, vice], ignore_index=True)


def main():
    if not SPONSOR_IN.exists():
        sys.exit(f"Missing {SPONSOR_IN}. Run source/clean/poll_sponsor_2024.py first.")

    sponsor = pd.read_parquet(SPONSOR_IN)
    cands = load_mayoral_candidates()
    print(f"Loaded sponsor: {len(sponsor):,} rows / "
          f"{sponsor['protocol'].nunique():,} protocols")
    print(f"Loaded 2024 mayoral candidate registry: {len(cands):,} candidates / "
          f"{cands['muni_id'].nunique():,} munis")

    a = route_a_cpf(sponsor, cands)
    b = route_b_committee(sponsor, cands)
    print(f"\nRoute A (CPF→PREFEITO):     {len(a):,} sponsor rows matched")
    print(f"Route B (committee CNPJ):   {len(b):,} sponsor rows tagged "
          f"({(b['committee_office']=='PREFEITO').sum():,} PREFEITO + "
          f"{(b['committee_office']=='VICEPREFEITO').sum():,} VICE-PREFEITO)")
    print(f"  Route B PREFEITO with name matching politico registry: "
          f"{b[(b['committee_office']=='PREFEITO') & b['cand_politico_id'].notna()]['protocol'].count():,}")
    print(f"  Route B PREFEITO with parsed name NOT in registry: "
          f"{b[(b['committee_office']=='PREFEITO') & b['cand_politico_id'].isna()]['protocol'].count():,} "
          "(non-standard committee naming or candidate not in cleaned panel)")

    # Reassemble full long table — Route A + Route B + untagged residue
    matched = pd.concat([a, b], ignore_index=True)
    matched_keys = matched[["protocol", "role", "sponsor_idx"]].drop_duplicates()
    unmatched = sponsor.merge(
        matched_keys, on=["protocol", "role", "sponsor_idx"],
        how="left", indicator=True,
    )
    unmatched = unmatched[unmatched["_merge"] == "left_only"].drop(columns="_merge").copy()
    for col in ["sponsor_route", "sponsor_candidate_name_parsed", "committee_office",
                "cand_cpf", "cand_party", "cand_votes", "cand_politico_id",
                "cand_name", "politico_norm"]:
        unmatched[col] = pd.NA

    out = pd.concat([matched, unmatched], ignore_index=True)
    # Drop the helper join column
    out = out.drop(columns=[c for c in ["parsed_norm", "politico_norm"] if c in out.columns])
    # Rename for the published schema
    out = out.rename(columns={
        "cand_cpf": "sponsor_candidate_cpf",
        "cand_party": "sponsor_candidate_party",
        "cand_votes": "sponsor_candidate_votes",
        "cand_politico_id": "sponsor_candidate_politico_id",
        "cand_name": "sponsor_candidate_name",
    })

    print(f"\nFinal table: {len(out):,} rows; sponsor_route distribution:")
    print(out["sponsor_route"].fillna("unmatched").value_counts().to_string())

    out.to_parquet(OUT, index=False)
    print(f"\nWrote {OUT}")

    # ── Headline: within-candidate overlap ────────────────────────────
    print("\n" + "="*72)
    print("HEADLINE: within-candidate overlap (the go/no-go number)")
    print("="*72)
    # Define "self-sponsored": this protocol has at least one sponsor row
    # whose sponsor_candidate_politico_id is set (Route A or Route B
    # PREFEITO). Map protocol → set of self-sponsoring candidates;
    # protocol → race (muni). For each race, who appears as both
    # self-sponsoring AND polled in another sponsor's poll in the same race.
    self_sponsored = out[out["sponsor_candidate_politico_id"].notna()][[
        "protocol", "sponsor_candidate_politico_id", "muni_id",
    ]].drop_duplicates()
    # All polls in races we care about
    race_protocols = (
        sponsor[["protocol", "muni_code_tse"]].drop_duplicates()
        .assign(muni_id=lambda d: d["muni_code_tse"].astype("Int64").astype(str))
        .drop(columns="muni_code_tse")
    )
    # Per-race: polls that ARE self-sponsored by candidate X vs polls in
    # the same race NOT sponsored by candidate X (= "other-sponsored from
    # the perspective of candidate X").
    self_count = self_sponsored.groupby(
        ["muni_id", "sponsor_candidate_politico_id"]
    )["protocol"].nunique().rename("self_polls")
    race_polls = race_protocols.groupby("muni_id")["protocol"].nunique().rename("race_polls")
    cand_race = self_count.reset_index().merge(race_polls.reset_index(), on="muni_id")
    cand_race["other_polls"] = cand_race["race_polls"] - cand_race["self_polls"]
    cand_race["has_both"] = (cand_race["self_polls"] >= 1) & (cand_race["other_polls"] >= 1)

    print(f"\nCandidates with ≥1 self-sponsored poll (Route A or B PREFEITO): "
          f"{cand_race.shape[0]:,}")
    print(f"  ... AND ≥1 other poll in the same race: {cand_race['has_both'].sum():,}")
    print(f"  ... AND ≥2 self-sponsored polls (within-candidate replication): "
          f"{(cand_race['self_polls']>=2).sum():,}")
    print(f"  ... AND ≥2 self + ≥1 other in same race: "
          f"{((cand_race['self_polls']>=2) & (cand_race['other_polls']>=1)).sum():,}")
    print(f"\nRoute A alone:")
    a_only = out[out["sponsor_route"]=="cpf"][[
        "protocol", "sponsor_candidate_politico_id", "muni_id"]].drop_duplicates()
    a_self_count = a_only.groupby(
        ["muni_id", "sponsor_candidate_politico_id"]
    )["protocol"].nunique()
    a_cand_race = a_self_count.reset_index(name="self_polls").merge(race_polls.reset_index(), on="muni_id")
    a_cand_race["other_polls"] = a_cand_race["race_polls"] - a_cand_race["self_polls"]
    print(f"  Route A candidates with ≥1 self-sponsored poll: {a_cand_race.shape[0]:,}")
    print(f"  ... AND ≥1 other poll in same race: "
          f"{((a_cand_race['self_polls']>=1) & (a_cand_race['other_polls']>=1)).sum():,}")


if __name__ == "__main__":
    main()
