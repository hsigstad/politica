"""Clean per-year TSE poll sponsor metadata and classify each sponsor as
a candidate / party / other actor.

INTENT: produce one long sponsor table per year, keyed by
(NR_PROTOCOLO_REGISTRO, role, sponsor_idx), with the four sponsor-route
classifications (A: cpf, B: committee, C: party CNPJ, D: party name)
merged in. This is the data input for the DOWNSTREAM_PROJECT project
(`projects/DOWNSTREAM_PROJECT/`).

REASONING: TSE PesqEle allows up to 6 contratantes per protocol and a
separate set of pagantes per protocol, so the canonical output must be
long, not protocol-wide. Collapsing to one-per-protocol would force a
"which sponsor wins" rule and lose the multi-sponsor structure (which
is itself a known evasion pattern: split a poll across two committees so
no single one looks dominant). Routes A-D need the year's candidate
registry + party-directorate CNPJ map; the route join happens in the
same script (in-memory) so there is only ONE poll-sponsor cleaner per
year. Previously split into `poll_sponsor_2024.py` (raw long) and
`poll_sponsor_2024_join.py` (route classification) as a sandbox
accommodation when the 2024 registry was unavailable on the laptop —
that split is retired.

ASSUMES (per year):
- DATA_DIR/TSE/{year}/pesquisa_contratante/ and
  DATA_DIR/TSE/{year}/pesquisa_pagante/ contain per-UF CSVs extracted
  from the TSE dadosabertos PesqEle companion zips.
- build/clean/poll_{year}.parquet exists — built by
  source/clean/poll.py from the per-UF TSE registry CSVs. Provides the
  mayoral-poll universe (one row per protocol with uf, muni_code_tse,
  municipality, institute, pollster_cnpj).
- build/clean/candidato.csv exists with the year's PREFEITO rows; CPFs
  zero-padded to 11 to undo legacy float-cast loss; columns: cpf, year,
  office, municipio_id, votes, party, politico_id (TSE long-schema names
  retained downstream of pipelines/politica clean).
- build/clean/politico.csv exists (politico_id → politico name lookup).
- build/clean/despesa_partidaria.csv exists with raw TSE schema columns:
  AA_EXERCICIO, DS_TP_ESFERA_PARTIDARIA, NR_CNPJ_PRESTADOR_CONTA,
  SG_PARTIDO, CD_MUNICIPIO.

Multi-year usage: iterate over YEARS (default [2020, 2024]). Override
via env var: ``YEARS="2020" python -m source.clean.poll_sponsor``.

Writes (per year):
  build/clean/poll_sponsor_{year}.parquet — long, one row per
    (protocol, role ∈ {contratante, pagante}, sponsor_idx) with:
      raw sponsor identifier, normalized CPF/CNPJ, id_type flag, amount,
      funding source, registry fields (uf, municipality, institute,
      pollster_cnpj), plus sponsor-route classification:
        sponsor_route ∈ {'cpf', 'committee', 'party', 'party_name', None}
        sponsor_candidate_cpf, sponsor_candidate_politico_id,
        sponsor_candidate_name, sponsor_candidate_name_parsed,
        sponsor_candidate_party, sponsor_candidate_votes,
        committee_office.

Per-year structural + route diagnostics printed to stdout. The headline
"within-candidate overlap" count (go/no-go for the FE design) is printed
at the end of each year.
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
DATA_DIR = Path(os.environ["DATA_DIR"])
BUILD_DIR = BASE_DIR / "build"
BUILD_CLEAN_DIR = BUILD_DIR / "clean"

# Year list: override via env var YEARS="2020,2024" or edit here. The
# script writes one parquet per year and prints diagnostics per year.
YEARS = [int(y) for y in os.environ.get("YEARS", "2020,2024").split(",")]


# ═══════════════════════════════════════════════════════════════════════
# Raw loaders (per-UF CSVs from DATA_DIR/TSE/{year}/; mayoral universe
# from build/clean/poll_{year}.parquet)
# ═══════════════════════════════════════════════════════════════════════


def load_sponsor_csvs(csv_dir: Path, role: str, year: int) -> pd.DataFrame:
    """Concat per-UF sponsor CSVs from an extracted TSE directory;
    drop the _BRASIL / _BR aggregates.

    Returns long table keyed by NR_PROTOCOLO_REGISTRO. role ∈ {"contratante",
    "pagante"}. Reads with sep=';' and encoding='latin-1' per TSE
    dadosabertos convention. CPF/CNPJ columns forced to string so leading
    zeros survive (a numeric dtype silently drops the leading 0 on ~22%
    of CNPJs).
    """
    if not csv_dir.exists():
        sys.exit(f"Missing {csv_dir}.")
    prefix = f"pesquisa_{role}_{year}"
    csvs = sorted(csv_dir.glob(f"{prefix}_*.csv"))
    csvs = [c for c in csvs if c.stem not in {f"{prefix}_BRASIL", f"{prefix}_BR"}]
    if not csvs:
        sys.exit(f"No per-UF CSVs matching {prefix}_*.csv in {csv_dir}.")
    id_str_cols = ["NR_CPF_CNPJ_CONTRATANTE", "NR_CPF_CNPJ_PAGANTE"]
    dfs: list[pd.DataFrame] = []
    for csv_path in csvs:
        df = pd.read_csv(
            csv_path, sep=";", encoding="latin-1",
            dtype={c: str for c in id_str_cols},
            low_memory=False,
        )
        dfs.append(df)
    out = pd.concat(dfs, ignore_index=True)
    out["role"] = role
    return out


def load_mayoral_registry(year: int) -> pd.DataFrame:
    """Read build/clean/poll_{year}.parquet (built by source/clean/poll.py).

    Returns one row per mayoral protocol with the columns needed by
    the sponsor join: protocol, uf, muni_code_tse, municipality,
    institute, pollster_cnpj.
    """
    poll_path = BUILD_CLEAN_DIR / f"poll_{year}.parquet"
    if not poll_path.exists():
        sys.exit(
            f"Missing {poll_path}. Run source/clean/poll.py first to "
            f"build the {year} mayoral poll registry."
        )
    return pd.read_parquet(poll_path)[[
        "protocol", "uf", "muni_code_tse", "municipality",
        "institute", "pollster_cnpj",
    ]]


# ═══════════════════════════════════════════════════════════════════════
# Normalization
# ═══════════════════════════════════════════════════════════════════════


def normalize_cpf_cnpj(s: pd.Series) -> pd.DataFrame:
    """Strip non-digits, classify by length, flag missing/invalid.

    Returns DataFrame with columns id_clean (zero-padded digit string or
    None) and id_type ∈ {"CPF", "CNPJ", "missing", "invalid"}.
    """
    raw = s.fillna("").astype(str).str.replace(r"\D", "", regex=True)
    id_type = pd.Series("invalid", index=raw.index, dtype="object")
    id_type[raw == ""] = "missing"
    id_type[raw.str.len() == 11] = "CPF"
    id_type[raw.str.len() == 14] = "CNPJ"
    id_clean = raw.where(raw != "", other=None)
    return pd.DataFrame({"id_clean": id_clean, "id_type": id_type})


def parse_brl(s: pd.Series) -> pd.Series:
    """TSE uses comma decimal separator ('4600,00')."""
    return pd.to_numeric(
        s.astype(str).str.replace(",", ".", regex=False),
        errors="coerce",
    )


def _norm_name(s: str) -> str:
    """Uppercase, ASCII-fold, drop punctuation, collapse whitespace.

    Used for cross-checking parsed committee names against the politico
    registry (Route B).
    """
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^A-Za-z0-9 ]", " ", s).upper().strip()
    return re.sub(r"\s+", " ", s)


# ═══════════════════════════════════════════════════════════════════════
# Long sponsor table (contratante + pagante stacked, registry attached)
# ═══════════════════════════════════════════════════════════════════════


def build_sponsor_long(
    contr: pd.DataFrame, pag: pd.DataFrame, reg: pd.DataFrame
) -> pd.DataFrame:
    """Stack contratante + pagante into one long sponsor table.

    Columns: protocol, role, sponsor_idx, sponsor_id_raw, sponsor_id,
    id_type, sponsor_name, amount_brl, origem_recurso,
    st_contratante_pagante (None for pagante rows — that field exists
    only on contratante), + registry fields from reg.
    """
    c = contr.rename(columns={
        "NR_PROTOCOLO_REGISTRO":      "protocol",
        "CD_CONTRATANTE":             "sponsor_idx",
        "NR_CPF_CNPJ_CONTRATANTE":    "sponsor_id_raw",
        "NM_CONTRATANTE":             "sponsor_name",
        "VR_PAGO_CONTRATANTE":        "amount_brl_raw",
        "ST_CONTRATANTE_PAGANTE":     "st_contratante_pagante",
        "DS_ORIGEM_RECURSO":          "origem_recurso",
    })[["protocol", "role", "sponsor_idx", "sponsor_id_raw", "sponsor_name",
        "amount_brl_raw", "st_contratante_pagante", "origem_recurso"]]

    p = pag.rename(columns={
        "NR_PROTOCOLO_REGISTRO":   "protocol",
        "CD_CONTRATANTE":          "sponsor_idx",
        "NR_CPF_CNPJ_PAGANTE":     "sponsor_id_raw",
        "NM_PAGANTE":              "sponsor_name",
        "DS_ORIGEM_RECURSO":       "origem_recurso",
    })[["protocol", "role", "sponsor_idx", "sponsor_id_raw", "sponsor_name",
        "origem_recurso"]]
    p["amount_brl_raw"] = pd.NA
    p["st_contratante_pagante"] = pd.NA

    sponsor = pd.concat([c, p], ignore_index=True)
    sponsor["amount_brl"] = parse_brl(sponsor["amount_brl_raw"])

    ids = normalize_cpf_cnpj(sponsor["sponsor_id_raw"])
    sponsor["sponsor_id"] = ids["id_clean"]
    sponsor["id_type"]    = ids["id_type"]

    sponsor = sponsor.merge(reg, on="protocol", how="left",
                            validate="many_to_one")
    return sponsor


# ═══════════════════════════════════════════════════════════════════════
# Candidate-route classification: Routes A (CPF), B (committee),
# C (party CNPJ), D (party name)
# ═══════════════════════════════════════════════════════════════════════


def load_mayoral_candidates(year: int) -> pd.DataFrame:
    """Per-year PREFEITO candidate panel with CPF, muni, party, votes,
    politico_id, and politico-joined name.

    candidato.csv stores year as float-cast string ("2024.0") and
    municipio_id with a trailing ".0" from the same legacy issue.
    CPFs are zero-padded to 11.
    """
    cand_path = BUILD_CLEAN_DIR / "candidato.csv"
    pol_path  = BUILD_CLEAN_DIR / "politico.csv"
    if not cand_path.exists():
        sys.exit(f"Missing {cand_path} — needed for sponsor-route join.")
    if not pol_path.exists():
        sys.exit(f"Missing {pol_path} — needed for sponsor-route join.")

    c = pd.read_csv(
        cand_path, dtype=str,
        usecols=["cpf", "year", "office", "municipio_id",
                 "votes", "party", "politico_id"],
    )
    c = c[(c["year"] == f"{year}.0") & (c["office"] == "PREFEITO")].copy()
    c["cpf"] = c["cpf"].fillna("").str.zfill(11)
    c["muni_id"] = c["municipio_id"].str.replace(r"\.0$", "", regex=True)

    p = pd.read_csv(pol_path, dtype=str, usecols=["politico_id", "politico"])
    c = c.merge(p, on="politico_id", how="left", validate="many_to_one")
    c["politico_norm"] = c["politico"].map(_norm_name)
    return c.rename(columns={
        "cpf":          "cand_cpf",
        "votes":        "cand_votes",
        "party":        "cand_party",
        "politico_id":  "cand_politico_id",
        "politico":     "cand_name",
    })[[
        "cand_cpf", "muni_id", "cand_party", "cand_votes",
        "cand_politico_id", "cand_name", "politico_norm",
    ]]


def route_a_cpf(sponsor: pd.DataFrame, cands: pd.DataFrame) -> pd.DataFrame:
    """Match sponsor rows where sponsor_id is a CPF to a PREFEITO
    candidate in the same muni. Returns the matched subset with cand_*
    columns appended.
    """
    s = sponsor[sponsor["id_type"] == "CPF"].copy()
    s["muni_id"] = s["muni_code_tse"].astype("Int64").astype(str)
    j = s.merge(
        cands, left_on=["sponsor_id", "muni_id"],
        right_on=["cand_cpf", "muni_id"], how="inner",
    )
    j["sponsor_route"] = "cpf"
    j["sponsor_candidate_name_parsed"] = pd.NA
    j["committee_office"] = pd.NA
    return j


def _committee_re(year: int) -> re.Pattern:
    """Year-specific committee-name regex.

    TSE's standard naming: "ELEICAO {YEAR} {NOME COMPLETO}
    {PREFEITO|VICE-PREFEITO}" (rendered without the ç in the sponsor
    table). The {NOME} is greedy but the trailing role suffix anchors
    the capture.
    """
    return re.compile(
        rf"ELEI[CÇ][AÃ]O\s+{year}\s+(.+?)\s+(VICE\s*-?\s*PREFEITO|PREFEITO)\s*$",
        re.IGNORECASE,
    )


def route_b_committee(
    sponsor: pd.DataFrame, cands: pd.DataFrame, year: int,
) -> pd.DataFrame:
    """Parse 'ELEICAO {year} {NOME} {PREFEITO|VICE-PREFEITO}' from the
    sponsor name; cross-check parsed name against candidato in the same
    muni (ASCII-folded uppercase). VICE-PREFEITO rows are tagged
    route=committee but NOT joined to a PREFEITO candidate.
    """
    committee_re = _committee_re(year)
    s = sponsor[sponsor["id_type"] == "CNPJ"].copy()
    parsed = s["sponsor_name"].fillna("").str.extract(committee_re)
    s["sponsor_candidate_name_parsed"] = parsed[0].str.strip()
    s["committee_office"] = (
        parsed[1].str.upper()
                 .str.replace(r"\s+", "", regex=True)
                 .str.replace("-", "", regex=False)
    )
    s = s[s["sponsor_candidate_name_parsed"].notna()].copy()
    s["parsed_norm"] = s["sponsor_candidate_name_parsed"].map(_norm_name)
    s["muni_id"] = s["muni_code_tse"].astype("Int64").astype(str)

    prefeito = s[s["committee_office"] == "PREFEITO"].copy()
    j = prefeito.merge(
        cands, left_on=["parsed_norm", "muni_id"],
        right_on=["politico_norm", "muni_id"], how="left",
    )
    j["sponsor_route"] = "committee"

    vice = s[s["committee_office"] == "VICEPREFEITO"].copy()
    for col in ["cand_cpf", "cand_party", "cand_votes",
                "cand_politico_id", "cand_name", "politico_norm"]:
        vice[col] = pd.NA
    vice["sponsor_route"] = "committee"

    return pd.concat([j, vice], ignore_index=True)


def load_party_cnpj_lookup(year: int) -> pd.DataFrame:
    """Per-year CNPJ → (party, muni_id) lookup from municipal-level
    party-directorate expense filings. Each municipal directorate has a
    unique CNPJ; dedupe to one row per CNPJ.
    """
    despesa_path = BUILD_CLEAN_DIR / "despesa_partidaria.csv"
    if not despesa_path.exists():
        print(f"Note: {despesa_path} not found — Route C will yield 0 matches.")
        return pd.DataFrame(columns=["cnpj", "party", "muni_id"])
    df = pd.read_csv(
        despesa_path, dtype=str,
        usecols=[
            "AA_EXERCICIO", "DS_TP_ESFERA_PARTIDARIA",
            "NR_CNPJ_PRESTADOR_CONTA", "SG_PARTIDO", "CD_MUNICIPIO",
        ],
    )
    df = df[
        (df["AA_EXERCICIO"] == str(year))
        & (df["DS_TP_ESFERA_PARTIDARIA"].str.contains("Municipal", case=False, na=False))
    ].copy()
    df["cnpj"]    = df["NR_CNPJ_PRESTADOR_CONTA"].str.replace(r"\D", "", regex=True)
    df["party"]   = df["SG_PARTIDO"]
    df["muni_id"] = df["CD_MUNICIPIO"]
    return df[["cnpj", "party", "muni_id"]].drop_duplicates(subset=["cnpj"])


def route_c_party_cnpj(
    sponsor: pd.DataFrame,
    cands: pd.DataFrame,
    already_matched_keys: pd.DataFrame,
    year: int,
) -> pd.DataFrame:
    """Match sponsor CNPJ → municipal party directorate → party's PREFEITO
    candidate in that muni. Only applies to CNPJ sponsors not already
    matched by Route A or B.
    """
    party_lu = load_party_cnpj_lookup(year)
    print(f"  Party CNPJ lookup: {len(party_lu):,} directorate CNPJs "
          f"across {party_lu['muni_id'].nunique():,} munis")

    s = sponsor[sponsor["id_type"] == "CNPJ"].copy()
    s["muni_id"] = s["muni_code_tse"].astype("Int64").astype(str)

    s = s.merge(
        already_matched_keys, on=["protocol", "role", "sponsor_idx"],
        how="left", indicator=True,
    )
    s = s[s["_merge"] == "left_only"].drop(columns="_merge")

    s = s.merge(party_lu, left_on="sponsor_id", right_on="cnpj", how="inner",
                suffixes=("", "_dir"))
    j = s.merge(
        cands, left_on=["party", "muni_id"],
        right_on=["cand_party", "muni_id"], how="inner",
    )
    j["sponsor_route"] = "party"
    j["sponsor_candidate_name_parsed"] = pd.NA
    j["committee_office"] = pd.NA
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
    then match to that party's PREFEITO candidate in the poll's muni.
    """
    s = sponsor[sponsor["id_type"] == "CNPJ"].copy()
    s["muni_id"] = s["muni_code_tse"].astype("Int64").astype(str)

    s = s.merge(
        already_matched_keys, on=["protocol", "role", "sponsor_idx"],
        how="left", indicator=True,
    )
    s = s[s["_merge"] == "left_only"].drop(columns="_merge")

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


# ═══════════════════════════════════════════════════════════════════════
# Per-year driver: raw load → long table → routes A-D → write
# ═══════════════════════════════════════════════════════════════════════


def clean_year(year: int) -> None:
    contr_dir = DATA_DIR / "TSE" / str(year) / "pesquisa_contratante"
    pag_dir   = DATA_DIR / "TSE" / str(year) / "pesquisa_pagante"

    print(f"\n{'=' * 72}")
    print(f"YEAR {year}")
    print(f"{'=' * 72}")
    print(f"Contratantes dir: {contr_dir}")
    print(f"Pagantes dir:     {pag_dir}\n")

    contr = load_sponsor_csvs(contr_dir, role="contratante", year=year)
    pag   = load_sponsor_csvs(pag_dir,   role="pagante", year=year)
    print(f"Loaded {len(contr):,} contratante rows, {len(pag):,} pagante rows.")

    reg = load_mayoral_registry(year)
    print(f"Loaded {len(reg):,} mayoral registry protocols from "
          f"build/clean/poll_{year}.parquet.")

    sponsor = build_sponsor_long(contr, pag, reg)
    print(f"Sponsor long-table: {len(sponsor):,} rows / "
          f"{sponsor['protocol'].nunique():,} protocols")

    cands = load_mayoral_candidates(year)
    print(f"Loaded {year} mayoral candidate registry: {len(cands):,} candidates / "
          f"{cands['muni_id'].nunique():,} munis")

    # ── Routes A & B ─────────────────────────────────────────────────
    a = route_a_cpf(sponsor, cands)
    b = route_b_committee(sponsor, cands, year)
    print(f"\nRoute A (CPF→PREFEITO):     {len(a):,} sponsor rows matched")
    print(f"Route B (committee CNPJ):   {len(b):,} sponsor rows tagged "
          f"({(b['committee_office']=='PREFEITO').sum():,} PREFEITO + "
          f"{(b['committee_office']=='VICEPREFEITO').sum():,} VICE-PREFEITO)")
    print(f"  Route B PREFEITO with name matching politico registry: "
          f"{b[(b['committee_office']=='PREFEITO') & b['cand_politico_id'].notna()]['protocol'].count():,}")
    print(f"  Route B PREFEITO with parsed name NOT in registry: "
          f"{b[(b['committee_office']=='PREFEITO') & b['cand_politico_id'].isna()]['protocol'].count():,} "
          "(non-standard committee naming or candidate not in cleaned panel)")

    # ── Route C ─────────────────────────────────────────────────────
    ab_keys = pd.concat([a, b], ignore_index=True)[
        ["protocol", "role", "sponsor_idx"]
    ].drop_duplicates()
    c = route_c_party_cnpj(sponsor, cands, ab_keys, year)
    print(f"Route C (party CNPJ→PREFEITO): {len(c):,} sponsor rows matched "
          f"({c['protocol'].nunique():,} protocols)")

    # ── Route D ─────────────────────────────────────────────────────
    abc_keys = pd.concat([a, b, c], ignore_index=True)[
        ["protocol", "role", "sponsor_idx"]
    ].drop_duplicates()
    d = route_d_party_name(sponsor, cands, abc_keys)
    print(f"Route D (party name→PREFEITO): {len(d):,} sponsor rows matched "
          f"({d['protocol'].nunique():,} protocols)")

    # ── Reassemble full long table: A+B+C+D + untagged residue ──────
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
    out = out.drop(columns=[c for c in ["parsed_norm", "politico_norm"] if c in out.columns])
    out = out.rename(columns={
        "cand_cpf":          "sponsor_candidate_cpf",
        "cand_party":        "sponsor_candidate_party",
        "cand_votes":        "sponsor_candidate_votes",
        "cand_politico_id":  "sponsor_candidate_politico_id",
        "cand_name":         "sponsor_candidate_name",
    })

    print(f"\nFinal table: {len(out):,} rows; sponsor_route distribution:")
    print(out["sponsor_route"].fillna("unmatched").value_counts().to_string())

    BUILD_CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    out_path = BUILD_CLEAN_DIR / f"poll_sponsor_{year}.parquet"
    out.to_parquet(out_path, index=False)
    print(f"\nWrote {out_path}")

    # ── Headline: within-candidate overlap ──────────────────────────
    print("\n" + "=" * 72)
    print(f"HEADLINE {year}: within-candidate overlap (go/no-go for FE design)")
    print("=" * 72)
    self_sponsored = out[out["sponsor_candidate_politico_id"].notna()][[
        "protocol", "sponsor_candidate_politico_id", "muni_id",
    ]].drop_duplicates()
    race_protocols = (
        sponsor[["protocol", "muni_code_tse"]].drop_duplicates()
        .assign(muni_id=lambda d: d["muni_code_tse"].astype("Int64").astype(str))
        .drop(columns="muni_code_tse")
    )
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
          f"{(cand_race['self_polls'] >= 2).sum():,}")
    print(f"  ... AND ≥2 self + ≥1 other in same race: "
          f"{((cand_race['self_polls'] >= 2) & (cand_race['other_polls'] >= 1)).sum():,}")

    a_only = out[out["sponsor_route"] == "cpf"][[
        "protocol", "sponsor_candidate_politico_id", "muni_id"]].drop_duplicates()
    a_self_count = a_only.groupby(
        ["muni_id", "sponsor_candidate_politico_id"]
    )["protocol"].nunique()
    a_cand_race = a_self_count.reset_index(name="self_polls").merge(
        race_polls.reset_index(), on="muni_id",
    )
    a_cand_race["other_polls"] = a_cand_race["race_polls"] - a_cand_race["self_polls"]
    print(f"\nRoute A alone:")
    print(f"  Route A candidates with ≥1 self-sponsored poll: {a_cand_race.shape[0]:,}")
    print(f"  ... AND ≥1 other poll in same race: "
          f"{((a_cand_race['self_polls'] >= 1) & (a_cand_race['other_polls'] >= 1)).sum():,}")


def main():
    for year in YEARS:
        clean_year(year)


if __name__ == "__main__":
    main()
