"""Channel E — firm-ownership (sócio) sponsor route.

INTENT: extend the sponsor→candidate routes A–D with a fifth route. A poll
whose contratante firm (CNPJ) has a prefeito or vice-prefeito candidate as a
sócio (partner) in the Receita Federal quadro societário — in the poll's own
muni — is counted as sponsored by that candidate:

    candidate CPF → sócio of firm → firm CNPJ → poll contratante → sponsored

REASONING: routes A–D catch a candidate who pays with their own CPF (A), a
committee-named CNPJ (B), or a party directorate (C/D). They miss a candidate
who pays through a company they own — an ordinary firm CNPJ with no committee
or party marker, so the poll looks independent. Firm ownership is observable:
the candidate appears as a sócio of that CNPJ.

`route_e_socio()` has the same (sponsor, cands, ..., year) shape as routes
A–D so it can be lifted into poll_sponsor.py's main() unchanged. Kept in its
own module for now so the shared cleaner (and its headline treated-set) is
not touched until integration is deliberately approved. Run standalone as a
diagnostic — it reports the count of new candidate-sponsored polls Channel E
adds over A–D and writes them to a separate file, without modifying
poll_sponsor_{year}.parquet:

    python pipelines/politica/source/clean/poll_sponsor_route_e.py

ASSUMES:
- build/clean/poll_sponsor_{year}.parquet exists (routes A–D applied), with
  protocol, role, sponsor_idx, sponsor_id, id_type, muni_code_tse,
  sponsor_route.
- build/clean/candidato.csv + politico.csv (PREFEITO + VICEPREFEITO rows,
  cpf zero-padded to 11, full legal name via politico_id).
- pipelines/cnpj/build/clean/socio_{snapshot}.parquet with (cnpj [8-digit
  base], nome_socio, cpf_cnpj_socio [RF-masked ***NNNNNN**], data_entrada).

DATA CAVEATS:
- RF masks person CPFs to the middle six digits, so the candidate↔sócio join
  is on those six PLUS an exact full-legal-name check (politico vs nome_socio,
  never nome_urna).
- Same-muni is required, as in routes A–D: a candidate-owned firm sponsoring a
  poll in a *different* muni is that candidate's firm doing business
  elsewhere, not self-sponsorship of their own race.
- No data_saida in the sócio table, so "still a partner at the election" can't
  be enforced; only data_entrada <= election is applied.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
POLITICA_ROOT = HERE.parents[1]           # pipelines/politica
WORKSPACE = POLITICA_ROOT.parents[1]      # workspace root
BUILD_CLEAN_DIR = POLITICA_ROOT / "build" / "clean"
CNPJ_CLEAN_DIR = WORKSPACE / "pipelines" / "cnpj" / "build" / "clean"

# Receita Federal sócios snapshot nearest to (and not after) each election.
SOCIO_PARQUET = {
    2020: CNPJ_CLEAN_DIR / "socio_202001.parquet",
    2024: CNPJ_CLEAN_DIR / "socio_20240812.parquet",
}
ELECTION_DATE = {2020: "2020-11-15", 2024: "2024-10-06"}


def _norm_name(s: str) -> str:
    """Uppercase, ASCII-fold, drop punctuation, collapse whitespace — matches
    poll_sponsor._norm_name so names align with the routes A–D convention."""
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^A-Za-z0-9 ]", " ", s).upper().strip()
    return re.sub(r"\s+", " ", s)


def load_slate_candidates(year: int) -> pd.DataFrame:
    """Prefeito + vice candidates with the fields Route E needs: the masked-
    CPF middle-6 key, normalized full legal name, office, coalition, and the
    cand_* columns the routes emit."""
    c = pd.read_csv(
        BUILD_CLEAN_DIR / "candidato.csv", dtype=str,
        usecols=["cpf", "year", "office", "municipio_id", "votes", "party",
                 "politico_id", "NUMERO_CAND"],
    )
    c = c[(c["year"] == f"{year}.0")
          & (c["office"].isin(["PREFEITO", "VICEPREFEITO"]))].copy()
    c["cpf"] = c["cpf"].fillna("").str.zfill(11)
    c["cpf6"] = c["cpf"].str[3:9]                      # middle six, RF-visible
    c["muni_id"] = c["municipio_id"].str.replace(r"\.0$", "", regex=True)
    # Ticket key: the prefeito and vice share the ballot number NUMERO_CAND.
    c["numero"] = c["NUMERO_CAND"].str.replace(r"\.0$", "", regex=True)
    p = pd.read_csv(BUILD_CLEAN_DIR / "politico.csv", dtype=str,
                    usecols=["politico_id", "politico"])
    c = c.merge(p, on="politico_id", how="left", validate="many_to_one")
    c["politico_norm"] = c["politico"].map(_norm_name)
    c = c[c["cpf6"].str.len() == 6]
    # Runoff rounds and candidacy substitutions produce several rows per ticket;
    # keep one per (muni, office, ticket) — the max-votes (final / substantive)
    # row — so the ticket key is unique per office.
    c["_votes_n"] = pd.to_numeric(c["votes"], errors="coerce").fillna(0)
    c = (c.sort_values("_votes_n")
           .drop_duplicates(["muni_id", "office", "numero"], keep="last")
           .drop(columns="_votes_n"))
    return c.rename(columns={
        "cpf": "cand_cpf", "votes": "cand_votes", "party": "cand_party",
        "politico_id": "cand_politico_id", "politico": "cand_name",
    })[["cand_cpf", "cpf6", "muni_id", "numero", "office", "cand_party",
        "cand_votes", "cand_politico_id", "cand_name", "politico_norm"]]


def _attribute_vice_to_mayor(link: pd.DataFrame, slate: pd.DataFrame) -> pd.DataFrame:
    """A vice-prefeito has no vote share, so a vice-owned firm is attributed to
    the prefeito on the same ticket (muni_id + coalition). Prefeito owners pass
    through unchanged; `office` records which side the link came from."""
    cand_cols = ["cand_cpf", "cand_party", "cand_votes", "cand_politico_id",
                 "cand_name", "politico_norm"]
    mayors = slate[slate["office"] == "PREFEITO"][["muni_id", "numero"] + cand_cols]
    is_vice = link["office"] == "VICEPREFEITO"
    direct = link[~is_vice].copy()
    viced = link[is_vice].drop(columns=cand_cols).merge(
        mayors, on=["muni_id", "numero"], how="inner", validate="many_to_one")
    return pd.concat([direct, viced], ignore_index=True)


def route_e_socio(
    sponsor: pd.DataFrame, slate: pd.DataFrame, socio: pd.DataFrame,
    already_keys: pd.DataFrame, year: int,
) -> pd.DataFrame:
    """Match an as-yet-unmatched CNPJ contratante to a prefeito/vice candidate
    who is a sócio of that firm, in the poll's own muni. Returns the matched
    sponsor rows with cand_* columns + sponsor_route='socio' appended,
    mirroring route_a's output shape."""
    s = sponsor[sponsor["id_type"] == "CNPJ"].copy()
    # Drop any route-output columns if a finished parquet was passed in, so the
    # ones this route emits don't collide (raw sponsor tables lack them).
    s = s.drop(columns=[col for col in [
        "sponsor_route", "sponsor_candidate_name_parsed", "committee_office",
        "sponsor_candidate_cpf", "sponsor_candidate_party", "sponsor_candidate_votes",
        "sponsor_candidate_politico_id", "sponsor_candidate_name",
    ] if col in s.columns])
    s = s.merge(already_keys, on=["protocol", "role", "sponsor_idx"],
                how="left", indicator=True, validate="many_to_one")
    s = s[s["_merge"] == "left_only"].drop(columns="_merge")
    s["cnpj8"] = s["sponsor_id"].astype(str).str.zfill(14).str[:8]
    s["muni_id"] = s["muni_code_tse"].astype("Int64").astype(str)

    soc = socio[socio["cnpj"].astype(str).str.zfill(8).isin(set(s["cnpj8"]))].copy()
    soc["cnpj8"] = soc["cnpj"].astype(str).str.zfill(8)
    soc["cpf6"] = soc["cpf_cnpj_socio"].astype(str).str.replace(r"\D", "", regex=True)
    soc = soc[soc["cpf6"].str.len() == 6]
    soc["socio_norm"] = soc["nome_socio"].map(_norm_name)

    # candidate ↔ sócio: middle-6 CPF + exact full-legal-name + pre-election
    link = slate.merge(soc[["cnpj8", "cpf6", "socio_norm", "data_entrada"]],
                       on="cpf6", how="inner", validate="many_to_many")
    link = link[link["politico_norm"] == link["socio_norm"]]
    link = link[link["data_entrada"].astype(str)
                <= ELECTION_DATE.get(year, f"{year}-10-06")]
    link = _attribute_vice_to_mayor(link, slate)

    # firm CNPJ8 → poll contratante, same muni (as in routes A–D)
    keep = ["cnpj8", "muni_id", "office", "cand_cpf", "cand_party", "cand_votes",
            "cand_politico_id", "cand_name", "politico_norm"]
    j = s.merge(link[keep].drop_duplicates(), on=["cnpj8", "muni_id"],
                how="inner", validate="many_to_many")
    j["sponsor_route"] = "socio"
    j["sponsor_candidate_name_parsed"] = pd.NA
    return j.rename(columns={"office": "committee_office"}).drop(columns="cnpj8")


def main() -> int:
    years = [2024]  # 2020 socio snapshot (Jan 2020) predates most registrations
    for year in years:
        ps_path = BUILD_CLEAN_DIR / f"poll_sponsor_{year}.parquet"
        if not ps_path.exists():
            print(f"skip {year}: {ps_path} not found")
            continue
        sponsor = pd.read_parquet(ps_path)
        already_keys = (sponsor[sponsor["sponsor_route"].notna()]
                        [["protocol", "role", "sponsor_idx"]].drop_duplicates())
        slate = load_slate_candidates(year)
        socio = pd.read_parquet(
            SOCIO_PARQUET[year],
            columns=["cnpj", "nome_socio", "cpf_cnpj_socio", "data_entrada"])

        e = route_e_socio(sponsor, slate, socio, already_keys, year)

        ad_polls = set(sponsor[sponsor["sponsor_route"].notna()
                               & sponsor["sponsor_candidate_politico_id"].notna()]["protocol"])
        e_polls = set(e["protocol"])
        print(f"\n=== Channel E (sócio firm-ownership), {year} ===")
        print(f"  sponsor rows matched: {len(e)}  |  firms: {e['sponsor_id'].nunique()}"
              f"  |  polls: {len(e_polls)}")
        print(f"  by owner office: {e.groupby('committee_office')['protocol'].nunique().to_dict()}")
        print(f"  NEW candidate-sponsored polls (not already via A–D): {len(e_polls - ad_polls)}")
        out = BUILD_CLEAN_DIR / f"poll_sponsor_route_e_{year}.parquet"
        e.to_parquet(out, index=False)
        print(f"  wrote {out} (diagnostic — poll_sponsor_{year}.parquet untouched)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
