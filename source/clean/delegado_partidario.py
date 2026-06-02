"""Clean TSE party-delegate (delegado partidário) data.

INTENT: Normalize per-party CSVs of credentialed party delegates into a
single parquet with consistent column names, typed dates, and cleaned text.

Input:  $DATA_DIR/TSE/2022/delegado_partidario/delegado_partidario_*.csv
Output: build/clean/delegado_partidario.parquet
"""
import os
from glob import glob

import pandas as pd

import path
import diarios.clean as clean


COLS = {
    'SG_PARTIDO': 'partido',
    'NR_PARTIDO': 'nr_partido',
    'NM_PARTIDO': 'nm_partido',
    'CD_TIPO_ABRANGENCIA': 'cd_abrangencia',
    'DS_TIPO_ABRANGENCIA': 'abrangencia',
    'SG_UF': 'estado',
    'SG_UE': 'sg_ue',
    'NM_UE': 'nm_ue',
    'SQ_DELEGADO': 'sq_delegado',
    'NR_TITULO_ELEITORAL': 'titulo_eleitoral',
    'NM_DELEGADO': 'nome',
    'DT_CREDENCIAMENTO': 'dt_credenciamento',
    'DT_DESCREDENCIAMENTO': 'dt_descredenciamento',
}

DATE_COLS = ['dt_credenciamento', 'dt_descredenciamento']

DROP_RAW = ['DT_GERACAO', 'HH_GERACAO']


def clean_file(infile):
    # ASSUMES: latin1 encoding and semicolon separator (standard TSE bulk).
    df = pd.read_csv(infile, encoding='latin1', sep=';', low_memory=False,
                     dtype={'NR_TITULO_ELEITORAL': str})
    df = df.rename(columns=COLS)
    keep = [c for c in COLS.values() if c in df.columns]
    df = df.loc[:, keep].copy()

    for c in DATE_COLS:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], format='%d/%m/%Y', errors='coerce')

    # REASONING: TSE uses 01/01/1900 as a sentinel for "no descredenciamento
    # date" (still active). Replace with NaT.
    if 'dt_descredenciamento' in df.columns:
        sentinel = pd.Timestamp('1900-01-01')
        df.loc[df['dt_descredenciamento'] == sentinel, 'dt_descredenciamento'] = pd.NaT

    if 'cd_abrangencia' in df.columns:
        df['cd_abrangencia'] = pd.to_numeric(
            df['cd_abrangencia'], errors='coerce').astype('Int64')

    df = clean.clean_text_columns(
        df, exclude=['estado', 'titulo_eleitoral'] + DATE_COLS
    )
    return df


def get_infiles():
    pattern = os.path.join(
        path.data_dir, 'TSE', '2022', 'delegado_partidario',
        'delegado_partidario_*.csv',
    )
    return sorted(glob(pattern))


if __name__ == '__main__':
    infiles = get_infiles()
    print(f'Found {len(infiles)} party files')
    if not infiles:
        raise SystemExit(
            f'No delegado_partidario CSVs found under {path.data_dir}/TSE/2022/')
    dfs = []
    for f in infiles:
        print(f'  {os.fsencode(os.path.basename(f))}')
        dfs.append(clean_file(f))
    df = pd.concat(dfs, ignore_index=True)

    out = path.build_clean_dir / 'delegado_partidario.parquet'
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    print(f'Wrote {len(df):,} rows to {out}')
