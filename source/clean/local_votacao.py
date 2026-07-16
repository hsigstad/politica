"""Clean: geocoded local de votação (voting station) panel, 2006-2024.

INTENT. One typed table of every Brazilian polling place (local de
votação) with its bairro and best-available coordinates, per election
year. This is the reusable electoral-geography primitive (repo_placement:
TSE-electoral → politica): downstream projects join votes / sample designs
to prior-election geography through it. Distinct grain from
`eleitorado_local_votacao` (that table is per *seção* and 2024-only); this
is per *local de votação* and spans 2006-2024, which is what makes prior
years (e.g. 2020) reachable.

REASONING. Source is F. D. Hidalgo's ML-geocoding of TSE polling places
(github.com/fdhidalgo/geocode_br_polling_stations, v0.15), which fills and
corrects coordinates that raw TSE/Google geocoding misses in the interior.
Hidalgo's `long`/`lat` already coalesce official TSE coordinates
(`tse_*`, when present) over the ML prediction (`pred_*`); we keep that
merged value and record which source won in `coord_source` so consumers
can filter on it. `pred_dist` (the ML place's distance to the nearest
matched administrative point) is carried as a geocode-quality proxy.

ASSUMES.
  - Raw staged at data/geocode_br_polling_stations/geocoded_polling_stations.csv.gz
    (gitignored; move to $DATA_DIR + bi-dropbox later — override with
    LOCAL_VOTACAO_RAW). One row per (cd_localidade_tse, ano, nr_zona,
    nr_locvot); verified unique on those keys.
  - `cd_localidade_tse` is the TSE município code (== municipio_id used by
    votacao_secao_*.parquet); the join key to votes is
    (municipio_id, zona, local_votacao).
"""
import os
from pathlib import Path

import pandas as pd

import path
import diarios.clean as clean

RAW = Path(os.environ.get(
    "LOCAL_VOTACAO_RAW",
    path.build_clean_dir.parents[1] / "data" / "geocode_br_polling_stations"
    / "geocoded_polling_stations.csv.gz"))

COLS = {
    "ano": "year",
    "sg_uf": "estado",
    "cd_localidade_tse": "municipio_id",
    "nm_localidade": "municipio",
    "nr_zona": "zona",
    "nr_locvot": "local_votacao",          # local NUMBER; matches votacao_secao_*.local_votacao
    "nm_locvot": "local_votacao_nome",
    "ds_bairro": "bairro",
    "ds_endereco": "endereco",
    "nr_cep": "cep",
}
KEYS = ["municipio_id", "year", "zona", "local_votacao"]


def build() -> pd.DataFrame:
    raw = pd.read_csv(RAW, compression="gzip", dtype=str)

    df = raw.rename(columns=COLS)[list(COLS.values())].copy()

    # Coordinates: Hidalgo's merged long/lat already prefers official TSE
    # over the ML prediction; carry it, and flag which source won so
    # consumers can restrict to official-only if they want.
    df["longitude"] = pd.to_numeric(raw["long"], errors="coerce")
    df["latitude"] = pd.to_numeric(raw["lat"], errors="coerce")
    df["coord_source"] = raw["tse_lat"].notna().map({True: "tse", False: "pred"})
    df["coord_pred_dist"] = pd.to_numeric(raw["pred_dist"], errors="coerce")

    # Types + shared cleaners. municipio_id is the TSE code; the ibge7
    # crosswalk keys on it numerically, so derive ibge7 before narrowing
    # municipio_id to Int64.
    df["municipio_id"] = pd.to_numeric(df["municipio_id"], errors="coerce")
    df["ibge7"] = clean.transform(df["municipio_id"], "municipio_id", "ibge7").astype("Int64")
    df["municipio_id"] = df["municipio_id"].astype("Int64")
    for c in ("year", "zona", "local_votacao"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    df = clean.clean_text_columns(df, exclude=["estado", "cep", "coord_source"])

    # Grain check: one row per (municipio_id, year, zona, local_votacao).
    dup = int(df.duplicated(KEYS).sum())
    if dup:
        raise AssertionError(f"{dup} duplicate rows on {KEYS} — grain is not unique")
    return df.sort_values(KEYS).reset_index(drop=True)


def main() -> None:
    if not RAW.exists():
        raise SystemExit(f"Raw not found: {RAW}\nStage the Hidalgo v0.15 CSV there (see data/.../SOURCE.txt).")
    df = build()
    out = path.build_clean_dir / "local_votacao.parquet"
    df.to_parquet(out, engine="pyarrow", index=False, compression="zstd")
    print(f"Wrote {out} ({len(df):,} rows, {df.year.nunique()} years, "
          f"{df.municipio_id.nunique():,} munis, {out.stat().st_size/1e6:.1f} MB)")
    print("coord_source:", df.coord_source.value_counts().to_dict())


if __name__ == "__main__":
    main()
