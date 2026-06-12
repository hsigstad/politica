"""Clean TSE party-affiliation profile (perfil de filiação partidária) data.

INTENT: Normalize the aggregate affiliate-count table (one row per
party × municipality × zone × demographic cell) into a single parquet
with consistent column names, ibge7 codes, and cleaned text.

Input:  $DATA_DIR/TSE/2022/perfil_filiacao_partidaria/perfil_filiacao_partidaria.csv
Output: build/clean/perfil_filiacao_partidaria.parquet
"""
import os

import pandas as pd

import path
import diarios.clean as clean


COLS = {
    'NR_ANO_MES': 'ano_mes',
    'NR_PARTIDO': 'nr_partido',
    'SG_PARTIDO': 'partido',
    'NM_PARTIDO': 'nm_partido',
    'SG_UF': 'estado',
    'CD_MUNICIPIO': 'municipio_id',
    'NM_MUNICIPIO': 'municipio',
    'NR_ZONA': 'zona',
    'CD_GENERO': 'cd_genero',
    'DS_GENERO': 'genero',
    'CD_FAIXA_ETARIA': 'cd_faixa_etaria',
    'DS_FAIXA_ETARIA': 'faixa_etaria',
    'CD_ESTADO_CIVIL': 'cd_estado_civil',
    'DS_ESTADO_CIVIL': 'estado_civil',
    'CD_GRAU_INSTRUCAO': 'cd_escolaridade',
    'DS_GRAU_INSTRUCAO': 'escolaridade',
    'CD_OBJETO_OCUPACAO': 'cd_ocupacao',
    'NM_OCUPACAO': 'ocupacao',
    'CD_RACA_COR': 'cd_raca',
    'DS_RACA_COR': 'raca',
    'CD_IDENTIDADE_GENERO': 'cd_identidade_genero',
    'DS_IDENTIDADE_GENERO': 'identidade_genero',
    'CD_QUILOMBOLA': 'cd_quilombola',
    'DS_QUILOMBOLA': 'quilombola',
    'CD_INTERPRETE_LIBRAS': 'cd_interprete_libras',
    'DS_INTERPRETE_LIBRAS': 'interprete_libras',
    'QT_FILIADO': 'qt_filiados',
}

DROP_RAW = ['DT_GERACAO', 'HH_GERACAO']

# All CD_* columns that use -1 as "NÃO INFORMADO" sentinel.
CODE_COLS = [
    'cd_genero', 'cd_faixa_etaria', 'cd_estado_civil', 'cd_escolaridade',
    'cd_ocupacao', 'cd_raca', 'cd_identidade_genero', 'cd_quilombola',
    'cd_interprete_libras',
]


def clean_data(infile):
    # ASSUMES: latin1 encoding and semicolon separator (standard TSE bulk).
    # REASONING: File is ~12M rows; low_memory=False avoids mixed-type warnings.
    df = pd.read_csv(infile, encoding='latin1', sep=';', low_memory=False,
                     dtype={'CD_MUNICIPIO': str})
    df = df.rename(columns=COLS)
    keep = [c for c in COLS.values() if c in df.columns]
    df = df.loc[:, keep].copy()

    # Replace -1 sentinel with NA across categorical codes.
    for c in CODE_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').astype('Int64')
            df.loc[df[c] == -1, c] = pd.NA

    if 'qt_filiados' in df.columns:
        df['qt_filiados'] = pd.to_numeric(df['qt_filiados'], errors='coerce').astype('Int64')

    if 'zona' in df.columns:
        df['zona'] = pd.to_numeric(df['zona'], errors='coerce').astype('Int64')

    # REASONING: clean.transform expects numeric municipio_id; cast from string.
    mun_numeric = pd.to_numeric(df['municipio_id'], errors='coerce')
    df['ibge7'] = clean.transform(mun_numeric, 'municipio_id', 'ibge7')

    df = clean.clean_text_columns(
        df, exclude=['estado', 'municipio_id']
    )
    return df


if __name__ == '__main__':
    infile = os.path.join(
        path.data_dir, 'TSE', '2022', 'perfil_filiacao_partidaria',
        'perfil_filiacao_partidaria.csv',
    )
    if not os.path.exists(infile):
        raise SystemExit(f'File not found: {infile}')
    print(f'Reading {infile}')
    df = clean_data(infile)

    out = path.build_clean_dir / 'perfil_filiacao_partidaria.parquet'
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    print(f'Wrote {len(df):,} rows to {out}')
