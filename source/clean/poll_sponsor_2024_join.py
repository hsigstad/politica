"""Join 2024 poll sponsors to mayoral candidates (Routes A + B + C + D).

Reads `build/clean/poll_sponsor_2024.parquet` (long sponsor table from
`poll_sponsor_2024.py`) and links each sponsor row to a specific 2024
PREFEITO candidate when one of the four routes applies:

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

  Route C — sponsor CNPJ belongs to a municipal party directorate
            (identified via despesa_partidaria). Mapped to the party's
            PREFEITO candidate in that muni (1:1 by the electoral-law
            constraint that each party fields at most one mayoral
            candidate per municipality).

  Route D — sponsor name contains a clear party identifier (full party
            name like "PARTIDO LIBERAL" or abbreviation in a structured
            context like "PL - CIDADE - UF - MUNICIPAL"). Parsed party
            is matched to that party's PREFEITO candidate in the poll's
            municipality. Catches state/national-level party organs and
            municipal directorates whose CNPJ wasn't in despesa_partidaria.

The within-candidate FE design is feasible if many candidates appear in
BOTH self-sponsored AND other-sponsored polls in their own race. The
script prints the headline overlap count at the end (per Route A, Route
B, and union).

Reads:
  - build/clean/poll_sponsor_2024.parquet
  - build/clean/candidato.csv  (year=2024, office=PREFEITO universe;
      CPFs zero-padded to 11 to undo legacy float-cast loss)
  - build/clean/politico.csv   (politico_id → name lookup)
  - build/clean/despesa_partidaria.csv  (party directorate CNPJs;
      2024 municipal-level rows used to build CNPJ → party × muni map)

Writes:
  - build/clean/poll_sponsor_2024_candidate.parquet
      Same rows as poll_sponsor_2024.parquet plus:
        sponsor_route ∈ {'cpf', 'committee', 'party', 'party_name', None}
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
DESPESA_CSV = BUILD_CLEAN / "despesa_partidaria.csv"
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


def load_party_cnpj_lookup() -> pd.DataFrame:
    """Build CNPJ → (party, muni_id) lookup from 2024 municipal-level
    party directorate expense filings. Each municipal directorate has a
    unique CNPJ; we deduplicate to one row per CNPJ."""
    df = pd.read_csv(
        DESPESA_CSV, dtype=str,
        usecols=[
            "AA_EXERCICIO", "DS_TP_ESFERA_PARTIDARIA",
            "NR_CNPJ_PRESTADOR_CONTA", "SG_PARTIDO", "CD_MUNICIPIO",
        ],
    )
    df = df[
        (df["AA_EXERCICIO"] == "2024")
        & (df["DS_TP_ESFERA_PARTIDARIA"].str.contains("Municipal", case=False, na=False))
    ].copy()
    # Strip CNPJ to digits only (should already be clean, but defensive)
    df["cnpj"] = df["NR_CNPJ_PRESTADOR_CONTA"].str.replace(r"\D", "", regex=True)
    df["party"] = df["SG_PARTIDO"]
    df["muni_id"] = df["CD_MUNICIPIO"]
    return df[["cnpj", "party", "muni_id"]].drop_duplicates(subset=["cnpj"])


def route_c_party_cnpj(
    sponsor: pd.DataFrame,
    cands: pd.DataFrame,
    already_matched_keys: pd.DataFrame,
) -> pd.DataFrame:
    """Match sponsor CNPJ → municipal party directorate → party's PREFEITO
    candidate in that muni. Only applies to CNPJ sponsors not already
    matched by Route B (committee)."""
    party_lu = load_party_cnpj_lookup()
    print(f"  Party CNPJ lookup: {len(party_lu):,} directorate CNPJs "
          f"across {party_lu['muni_id'].nunique():,} munis")

    s = sponsor[sponsor["id_type"] == "CNPJ"].copy()
    s["muni_id"] = s["muni_code_tse"].astype("Int64").astype(str)

    # Exclude rows already matched by Route A or B
    s = s.merge(
        already_matched_keys, on=["protocol", "role", "sponsor_idx"],
        how="left", indicator=True,
    )
    s = s[s["_merge"] == "left_only"].drop(columns="_merge")

    # Join sponsor CNPJ → party directorate
    s = s.merge(party_lu, left_on="sponsor_id", right_on="cnpj", how="inner",
                suffixes=("", "_dir"))

    # Join party + muni → PREFEITO candidate
    j = s.merge(
        cands, left_on=["party", "muni_id"], right_on=["cand_party", "muni_id"],
        how="inner",
    )
    j["sponsor_route"] = "party"
    j["sponsor_candidate_name_parsed"] = pd.NA
    j["committee_office"] = pd.NA
    # Drop helper columns from the directorate lookup
    j = j.drop(columns=[c for c in ["cnpj", "party"] if c in j.columns])
    return j


# ── Route D helpers ──────────────────────────────────────────────────
# Only match sponsor names that clearly identify a political party —
# either a full party name ("PARTIDO LIBERAL") or a party abbreviation
# in structured TSE-style context ("PL - CIDADE - UF - MUNICIPAL").
PARTY_CONTEXT_RE = re.compile(
    r"PARTIDO|DIRET[OÓ]RIO|COMISS[AÃ]O PROVIS|"
    r"\b(?:PT|MDB|PSDB|PP|PL|PSD|PDT|PSB|PSOL|PV|PRD|PMN|PRTB|DC|PMB|"
    r"AGIR|MOBILIZA|UP|NOVO|PODE|AVANTE|CIDADANIA|REPUBLICANOS|"
    r"SOLIDARIEDADE|UNI[AÃ]O)"
    r"\s*-\s*\w+\s*-\s*[A-Z]{2}\s*-\s*(?:MUNICIPAL|ESTADUAL|NACIONAL)",
    re.IGNORECASE,
)

# Full party names → canonical abbreviation (checked longest-first).
_PARTY_FULL = {
    "PARTIDO DA SOCIAL DEMOCRACIA BRASILEIRA": "PSDB",
    "PARTIDO DO MOVIMENTO DEMOCRATICO BRASILEIRO": "MDB",
    "MOVIMENTO DEMOCRATICO BRASILEIRO": "MDB",
    "PARTIDO DA MOBILIZACAO NACIONAL": "MOBILIZA",
    "PARTIDO REPUBLICANO BRASILEIRO": "REPUBLICANOS",
    "PARTIDO RENOVACAO DEMOCRATICA": "PRD",
    "PARTIDO DEMOCRATICO TRABALHISTA": "PDT",
    "PARTIDO SOCIALISTA BRASILEIRO": "PSB",
    "PARTIDO SOCIAL DEMOCRATICO": "PSD",
    "PARTIDO PROGRESSISTA": "PP",
    "PARTIDO LIBERAL": "PL",
    "PARTIDO DOS TRABALHADORES": "PT",
    "PARTIDO VERDE": "PV",
    "UNIAO BRASIL": "UNIÃO",
    "PROGRESSISTAS": "PP",
}
_PARTY_FULL_SORTED = sorted(_PARTY_FULL.items(), key=lambda x: -len(x[0]))

# Abbreviations tried after full-name extraction fails.  Longer first
# so that PSDB is tried before PSD, REPUBLICANOS before RE, etc.
_ABBREVS = [
    "REPUBLICANOS", "SOLIDARIEDADE", "CIDADANIA", "MOBILIZA",
    "AVANTE", "PODE", "PSDB", "PSOL", "PRTB", "NOVO",
    "AGIR", "MDB", "PDT", "PSB", "PSD", "PMN", "PMB",
    "PRD", "PP", "PL", "PT", "PV", "DC", "UP", "UNIÃO",
]


def _extract_party_from_name(name: str) -> str | None:
    """Return the canonical party abbreviation if *name* unambiguously
    identifies a political party, else None."""
    if not isinstance(name, str):
        return None
    u = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").upper()
    for full, sig in _PARTY_FULL_SORTED:
        if full in u:
            return sig
    for a in _ABBREVS:
        if re.search(r"(?:^|[\s/(–-])" + re.escape(a) + r"(?:[\s/)–-]|$)", u):
            return a
    return None


def route_d_party_name(
    sponsor: pd.DataFrame,
    cands: pd.DataFrame,
    already_matched_keys: pd.DataFrame,
) -> pd.DataFrame:
    """Parse party from sponsor_name for rows with clear party context,
    then match to that party's PREFEITO candidate in the poll's muni."""
    s = sponsor[sponsor["id_type"] == "CNPJ"].copy()
    s["muni_id"] = s["muni_code_tse"].astype("Int64").astype(str)

    # Exclude rows already matched by earlier routes
    s = s.merge(
        already_matched_keys, on=["protocol", "role", "sponsor_idx"],
        how="left", indicator=True,
    )
    s = s[s["_merge"] == "left_only"].drop(columns="_merge")

    # Only consider rows whose name has clear party context
    s = s[s["sponsor_name"].fillna("").apply(
        lambda x: bool(PARTY_CONTEXT_RE.search(x))
    )].copy()

    s["parsed_party"] = s["sponsor_name"].apply(_extract_party_from_name)
    # PODE is the candidato-table spelling of PODEMOS
    s.loc[s["parsed_party"] == "PODEMOS", "parsed_party"] = "PODE"
    s = s[s["parsed_party"].notna()].copy()

    j = s.merge(
        cands, left_on=["parsed_party", "muni_id"],
        right_on=["cand_party", "muni_id"], how="inner",
    )
    j["sponsor_route"] = "party_name"
    j["sponsor_candidate_name_parsed"] = pd.NA
    j["committee_office"] = pd.NA
    j = j.drop(columns=[c for c in ["parsed_party"] if c in j.columns])
    return j


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

    ab_keys = pd.concat([a, b], ignore_index=True)[
        ["protocol", "role", "sponsor_idx"]
    ].drop_duplicates()
    c = route_c_party_cnpj(sponsor, cands, ab_keys)
    print(f"Route C (party CNPJ→PREFEITO): {len(c):,} sponsor rows matched "
          f"({c['protocol'].nunique():,} protocols)")

    abc_keys = pd.concat([a, b, c], ignore_index=True)[
        ["protocol", "role", "sponsor_idx"]
    ].drop_duplicates()
    d = route_d_party_name(sponsor, cands, abc_keys)
    print(f"Route D (party name→PREFEITO): {len(d):,} sponsor rows matched "
          f"({d['protocol'].nunique():,} protocols)")

    # Reassemble full long table — Routes A+B+C+D + untagged residue
    matched = pd.concat([a, b, c, d], ignore_index=True)
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
