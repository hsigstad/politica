"""Clean 2024 poll sponsor metadata: who commissioned and who paid for
each registered TSE mayoral poll.

Reads the TSE PesqEle companion CSVs (`pesquisa_contratante_2024` and
`pesquisa_pagante_2024`, distributed alongside the main poll registry on
TSE dadosabertos) and emits a long sponsor table keyed by
NR_PROTOCOLO_REGISTRO. Up to 6 contratantes and a separate set of
pagantes per protocol, so the parquet is long, not protocol-wide.

This is the data input for the DOWNSTREAM_PROJECT idea
(`research/DOWNSTREAM_PROJECT`). The CPF/CNPJ → candidate/party
classification is intentionally NOT done here — it requires the TSE
2024 candidate registry (`consulta_cand_2024`), which on this laptop
sandbox is absent. The raw `NR_CPF_CNPJ_*` is kept verbatim so a
downstream script (run on a separate host, where the 2024 registry lives) can
do the join.

Reads (sandbox layout):
  - DATA_DIR/tse/pesquisa_contratante_2024.zip
  - DATA_DIR/tse/pesquisa_pagante_2024.zip
  - path.tse_polls_2024_dir/pesquisa_eleitoral_2024_*.csv (registry,
    mayoral subset; falls back to $DATA_DIR
    when the canonical build/scrape location is empty — the laptop
    sandbox stages the registry under data_local/, not build/scrape/.)

Writes:
  - build/clean/poll_sponsor_2024.parquet     Long: one row per
    (protocol, role ∈ {contratante, pagante}, sponsor_idx) with the raw
    sponsor identifier, normalized CPF/CNPJ, id_type flag, amount,
    funding source, and a small set of registry fields needed
    downstream (uf, municipality, institute, institute_cnpj).

Structural diagnostics printed to stdout — sponsor-id mix (CPF / CNPJ /
missing), DS_ORIGEM_RECURSO cross-tab, top sponsor names by frequency,
institutional-sponsor share (sponsor CNPJ == pollster CNPJ), and merge
rate to the mayoral registry. The within-candidate overlap (the
load-bearing go/no-go number for the within-candidate FE design) cannot
be computed here without the 2024 candidate registry — deferred to
a separate host.
"""
from __future__ import annotations

import io
import os
import sys
import zipfile
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(os.environ["BASE_DIR"])
DATA_DIR = Path(os.environ["DATA_DIR"])
BUILD_DIR = BASE_DIR / "build"
BUILD_CLEAN_DIR = BUILD_DIR / "clean"
CANONICAL_REGISTRY_DIR = BUILD_DIR / "scrape" / "tse_polls_2024"
SANDBOX_REGISTRY_FALLBACK = Path("$DATA_DIR")


def find_registry_dir() -> Path:
    """Locate the TSE poll registry directory.

    Canonical location is BUILD/scrape/tse_polls_2024 (per
    pipelines/politica/path.py); laptop sandbox stages it under
    $DATA_DIR Use whichever is populated.
    """
    if CANONICAL_REGISTRY_DIR.exists() and any(
        CANONICAL_REGISTRY_DIR.glob("pesquisa_eleitoral_*.csv")
    ):
        return CANONICAL_REGISTRY_DIR
    if SANDBOX_REGISTRY_FALLBACK.exists() and any(
        SANDBOX_REGISTRY_FALLBACK.glob("pesquisa_eleitoral_*.csv")
    ):
        return SANDBOX_REGISTRY_FALLBACK
    sys.exit(
        f"No registry CSVs in {CANONICAL_REGISTRY_DIR} or "
        f"{SANDBOX_REGISTRY_FALLBACK}. Stage the 2024 poll registry "
        "CSVs before running."
    )


def load_sponsor_zip(zip_path: Path, role: str) -> pd.DataFrame:
    """Concat per-UF sponsor CSVs from a TSE zip; drop the _BRASIL aggregate.

    Returns long table keyed by NR_PROTOCOLO_REGISTRO. role ∈ {"contratante",
    "pagante"}. Reads with sep=';' and encoding='latin-1' per TSE
    dadosabertos convention.
    """
    if not zip_path.exists():
        sys.exit(f"Missing {zip_path}.")
    # Force CPF/CNPJ columns to string so leading zeros survive — TSE
    # stores them as plain digit strings and a numeric dtype silently
    # drops the leading 0 on ~22% of CNPJs (length-13/12/... rows).
    id_str_cols = ["NR_CPF_CNPJ_CONTRATANTE", "NR_CPF_CNPJ_PAGANTE"]
    dfs: list[pd.DataFrame] = []
    with zipfile.ZipFile(zip_path) as zf:
        members = [
            n for n in zf.namelist()
            if n.endswith(".csv") and "_BRASIL" not in n and "_BR.csv" not in n
        ]
        for name in sorted(members):
            with zf.open(name) as fh:
                df = pd.read_csv(
                    io.TextIOWrapper(fh, encoding="latin-1"),
                    sep=";",
                    dtype={c: str for c in id_str_cols},
                    low_memory=False,
                )
            dfs.append(df)
    out = pd.concat(dfs, ignore_index=True)
    out["role"] = role
    return out


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


def load_mayoral_registry(registry_dir: Path) -> pd.DataFrame:
    """Concat per-UF poll-registration CSVs, filter to mayoral subset.

    Keeps only the columns we need to (a) flag mayoral polls in the
    sponsor join and (b) detect institutional sponsoring (sponsor CNPJ
    == pollster CNPJ).
    """
    csvs = sorted(registry_dir.glob("pesquisa_eleitoral_*.csv"))
    csvs = [c for c in csvs if "_BRASIL" not in c.stem and "_BR" != c.stem[-3:]]
    if not csvs:
        sys.exit(f"No per-UF registry CSVs in {registry_dir}.")
    keep = [
        "NR_PROTOCOLO_REGISTRO",
        "DS_CARGO",
        "SG_UF",
        "SG_UE",
        "NM_UE",
        "NR_CNPJ_EMPRESA",
        "NM_EMPRESA",
    ]
    dfs = [
        pd.read_csv(c, sep=";", encoding="latin-1",
                    low_memory=False, usecols=keep,
                    dtype={"NR_CNPJ_EMPRESA": str})
        for c in csvs
    ]
    reg = pd.concat(dfs, ignore_index=True)
    reg = reg[reg["DS_CARGO"].str.contains("Prefeito", na=False, case=False)].copy()
    # A protocol can appear in multiple per-UF rows if the poll covers
    # multi-cargo races; collapse to one row per protocol on the kept
    # columns (they are constant within protocol for mayoral subset).
    reg = reg.drop_duplicates("NR_PROTOCOLO_REGISTRO")
    reg["pollster_cnpj"] = (
        reg["NR_CNPJ_EMPRESA"].astype(str).str.replace(r"\D", "", regex=True)
    )
    reg = reg.rename(columns={
        "NR_PROTOCOLO_REGISTRO": "protocol",
        "SG_UF":                 "uf",
        "SG_UE":                 "muni_code_tse",
        "NM_UE":                 "municipality",
        "NM_EMPRESA":            "institute",
    })[["protocol", "uf", "muni_code_tse", "municipality",
        "institute", "pollster_cnpj"]]
    return reg


def parse_brl(s: pd.Series) -> pd.Series:
    """TSE uses comma decimal separator ('4600,00')."""
    return pd.to_numeric(
        s.astype(str).str.replace(",", ".", regex=False),
        errors="coerce",
    )


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

    # Left-merge so non-mayoral sponsor rows survive but get NaN
    # registry fields — they'll be filtered (or kept) by downstream
    # consumers; we want to preserve total counts for diagnostics.
    sponsor = sponsor.merge(reg, on="protocol", how="left",
                            validate="many_to_one")
    return sponsor


def print_diagnostics(sponsor: pd.DataFrame, reg: pd.DataFrame) -> None:
    print("=" * 72)
    print("STEP 1 STRUCTURAL DIAGNOSTICS — poll_sponsor_2024")
    print("=" * 72)

    n_proto_reg = reg["protocol"].nunique()
    print(f"\nMayoral registry protocols:                       {n_proto_reg:>7,}")

    mayoral = sponsor[sponsor["uf"].notna()].copy()
    for role in ["contratante", "pagante"]:
        sub = sponsor[sponsor["role"] == role]
        sub_may = mayoral[mayoral["role"] == role]
        print(f"\n[{role}]")
        print(f"  rows (all polls):                               {len(sub):>7,}")
        print(f"  rows (mayoral polls):                           {len(sub_may):>7,}")
        print(f"  unique protocols w/ ≥1 {role} (mayoral):   "
              f"     {sub_may['protocol'].nunique():>7,}")
        print(f"  id_type distribution (mayoral):")
        for k, v in sub_may["id_type"].value_counts(dropna=False).items():
            print(f"    {k:<8} {v:>7,}  ({v / max(len(sub_may), 1):>5.1%})")
        if role == "contratante":
            print(f"  ST_CONTRATANTE_PAGANTE distribution (mayoral):")
            for k, v in sub_may["st_contratante_pagante"].value_counts(
                    dropna=False).items():
                print(f"    {k!s:<8} {v:>7,}")

    print(f"\nDS_ORIGEM_RECURSO × role (mayoral rows):")
    xt = pd.crosstab(
        mayoral["origem_recurso"].fillna("(missing)"),
        mayoral["role"],
        margins=True, margins_name="ALL",
    )
    print(xt.to_string())

    # Institutional sponsoring: sponsor CNPJ == pollster CNPJ on that poll
    inst = mayoral.copy()
    inst["is_institutional"] = (
        (inst["id_type"] == "CNPJ") &
        (inst["sponsor_id"] == inst["pollster_cnpj"])
    )
    inst_by_role = inst.groupby("role")["is_institutional"].agg(["sum", "count"])
    inst_by_role["share"] = inst_by_role["sum"] / inst_by_role["count"]
    print(f"\nInstitutional (sponsor CNPJ == pollster CNPJ), mayoral rows:")
    print(inst_by_role.to_string())

    # Protocols with any candidate-CPF sponsor — partial view of treated set.
    # We can't say WHICH candidate without the 2024 registry, but we can count
    # protocols whose contratante or pagante is a CPF (i.e., an individual).
    cpf_sponsor_protos = (
        mayoral[mayoral["id_type"] == "CPF"]["protocol"].unique()
    )
    print(f"\nProtocols with ≥1 individual (CPF) sponsor (mayoral): "
          f"{len(cpf_sponsor_protos):,} of {n_proto_reg:,} "
          f"({len(cpf_sponsor_protos) / max(n_proto_reg, 1):.1%})")

    print(f"\nTop 25 contratante names by # mayoral protocols:")
    top = (
        mayoral[mayoral["role"] == "contratante"]
        .groupby("sponsor_name")["protocol"].nunique()
        .sort_values(ascending=False).head(25)
    )
    print(top.to_string())

    # Merge-rate check: sponsor rows whose protocol is NOT in mayoral registry
    n_non_mayoral = sponsor["uf"].isna().sum()
    print(f"\nSponsor rows with no mayoral registry match: {n_non_mayoral:,} "
          f"(these are non-mayoral polls; sponsor zips cover all cargos).")

    # Within-race CPF diversity — candidate-agnostic proxy for the
    # within-candidate FE design's power. Without the 2024 candidato
    # registry we can't say if a CPF is a candidate or another
    # individual, but races with ≥2 distinct CPF sponsors are the ones
    # where a within-candidate comparison could ever exist.
    cpf = mayoral[mayoral["id_type"] == "CPF"].copy()
    race_cols = ["uf", "muni_code_tse"]
    by_race = (
        cpf.groupby(race_cols)
        .agg(n_polls_with_cpf=("protocol", "nunique"),
             n_distinct_cpf=("sponsor_id", "nunique"))
        .reset_index()
    )
    n_races_any_cpf = len(by_race)
    n_races_2plus_polls = (by_race["n_polls_with_cpf"] >= 2).sum()
    n_races_2plus_cpfs = (by_race["n_distinct_cpf"] >= 2).sum()
    print(f"\nWithin-race CPF diversity (candidate-agnostic proxy):")
    print(f"  races with ≥1 CPF-sponsored poll:        {n_races_any_cpf:>5,}")
    print(f"  races with ≥2 CPF-sponsored polls:       {n_races_2plus_polls:>5,}")
    print(f"  races with ≥2 *distinct* CPF sponsors:   {n_races_2plus_cpfs:>5,}")
    print(f"  (the last row caps the within-candidate FE sample at the race level)")


def main():
    contr_zip = DATA_DIR / "tse" / "pesquisa_contratante_2024.zip"
    pag_zip   = DATA_DIR / "tse" / "pesquisa_pagante_2024.zip"

    registry_dir = find_registry_dir()
    print(f"Registry dir: {registry_dir}")
    print(f"Contratantes zip: {contr_zip}")
    print(f"Pagantes zip:     {pag_zip}\n")

    contr = load_sponsor_zip(contr_zip, role="contratante")
    pag   = load_sponsor_zip(pag_zip,   role="pagante")
    print(f"Loaded {len(contr):,} contratante rows, {len(pag):,} pagante rows.")

    reg = load_mayoral_registry(registry_dir)
    print(f"Loaded {len(reg):,} mayoral registry protocols.")

    sponsor = build_sponsor_long(contr, pag, reg)

    BUILD_CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    out_path = BUILD_CLEAN_DIR / "poll_sponsor_2024.parquet"
    sponsor.to_parquet(out_path, index=False)
    print(f"\nWrote {len(sponsor):,} sponsor rows → {out_path}")

    print_diagnostics(sponsor, reg)


if __name__ == "__main__":
    main()
