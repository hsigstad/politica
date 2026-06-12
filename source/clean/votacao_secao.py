"""Clean votacao_secao (section-level election results) for 2020 and 2024.

Reads per-UF zips from DATA_DIR/TSE/{year}/votacao_secao/, joins
politico_id from candidato.csv via SQ_CANDIDATO, and writes one
compact parquet per year to build/clean/.

Output columns
--------------
year, round, estado, municipio_id, zona, secao, local_votacao,
office, nr_votavel, politico_id, party, votos
"""

import os
import re
import zipfile
from glob import glob

import pandas as pd

import path

YEARS = [2020, 2024]

# -- column mapping (same schema both years) --------------------------------
KEEP_COLS = {
    "ANO_ELEICAO": "year",
    "NR_TURNO": "round",
    "SG_UF": "estado",
    "CD_MUNICIPIO": "municipio_id",
    "NR_ZONA": "zona",
    "NR_SECAO": "secao",
    "NR_LOCAL_VOTACAO": "local_votacao",
    "CD_CARGO": "office_cd",
    "DS_CARGO": "office",
    "NR_VOTAVEL": "nr_votavel",
    "NM_VOTAVEL": "nm_votavel",
    "SQ_CANDIDATO": "sq_candidato",
    "QT_VOTOS": "votos",
}


def load_candidato_lookup():
    """Load (year, SQ_CANDIDATO) -> (politico_id, party) from candidato.csv."""
    df = pd.read_csv(
        path.build_clean_dir / "candidato.csv",
        usecols=["year", "SQ_CANDIDATO", "politico_id", "party"],
        dtype={"SQ_CANDIDATO": str, "politico_id": str, "party": str},
    )
    df["year"] = df["year"].astype("Int64")
    df = df.rename(columns={"SQ_CANDIDATO": "sq_candidato"})
    # candidato.csv stores SQ as float → "12345.0"; strip the decimal
    df["sq_candidato"] = df["sq_candidato"].str.replace(r"\.0$", "", regex=True)
    df = df.drop_duplicates(subset=["year", "sq_candidato"])
    return df


def read_zip(zippath):
    """Read the single CSV inside a votacao_secao zip."""
    with zipfile.ZipFile(zippath) as z:
        csv_name = z.namelist()[0]
        with z.open(csv_name) as f:
            df = pd.read_csv(
                f,
                encoding="latin-1",
                sep=";",
                usecols=list(KEEP_COLS.keys()),
                dtype={
                    "SQ_CANDIDATO": str,
                    "NR_VOTAVEL": str,
                    "CD_MUNICIPIO": str,
                    "NR_ZONA": str,
                    "NR_SECAO": str,
                    "NR_LOCAL_VOTACAO": str,
                    "CD_CARGO": str,
                },
            )
    df = df.rename(columns=KEEP_COLS)
    return df


def clean_year(year, cand_lookup):
    """Read all UF zips for one year, join politico_id, write parquet."""
    pattern = os.path.join(
        path.data_dir, "TSE", str(year), "votacao_secao",
        f"votacao_secao_{year}_*.zip",
    )
    zips = sorted(glob(pattern))
    if not zips:
        print(f"  No files found for {year}, skipping")
        return

    print(f"  Reading {len(zips)} UF zips for {year}...")
    chunks = []
    for zp in zips:
        uf = re.search(r"_([A-Z]{2})\.zip$", zp).group(1)
        print(f"    {uf}", end=" ", flush=True)
        chunks.append(read_zip(zp))
    print()

    df = pd.concat(chunks, ignore_index=True)
    del chunks

    # Coerce types
    df["year"] = year  # constant within file, written as parquet metadata
    df["round"] = df["round"].astype("Int8")
    df["votos"] = pd.to_numeric(df["votos"], errors="coerce").astype("Int16")

    # Numeric location IDs (smaller than string categoricals)
    for col in ["municipio_id", "zona", "secao", "local_votacao"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("UInt32")

    # Normalize office text
    df["office"] = df["office"].str.strip().str.upper()

    # Join politico_id + party from candidato.csv
    # sq_candidato = "-1" or "-3" for special entries (branco/nulo/legenda)
    year_cand = cand_lookup[cand_lookup["year"] == year].drop(columns="year")
    df = df.merge(year_cand, on="sq_candidato", how="left")

    # Drop columns redundant after join
    df = df.drop(columns=["office_cd", "nm_votavel", "sq_candidato"])

    # Categoricals for compression
    for col in ["estado", "office", "nr_votavel", "party"]:
        if col in df.columns:
            df[col] = df[col].astype("category")
    df["politico_id"] = df["politico_id"].astype("category")

    outfile = path.build_clean_dir / f"votacao_secao_{year}.parquet"
    df.to_parquet(outfile, engine="pyarrow", index=False,
                  compression="zstd")
    size_mb = outfile.stat().st_size / 1e6
    print(f"  Wrote {outfile} ({len(df):,} rows, {size_mb:.1f} MB)")


def main():
    print("Loading candidato lookup...")
    cand_lookup = load_candidato_lookup()
    for year in YEARS:
        print(f"\n--- {year} ---")
        clean_year(year, cand_lookup)


if __name__ == "__main__":
    main()
