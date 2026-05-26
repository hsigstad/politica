"""Clean TSE bulk electoral-appeal (recurso) metadata.

Reads `recurso_eleitoral_{year}.csv` / `recursos_eleitorais_{year}.csv`
bundles from dadosabertos.tse.jus.br and writes one normalized CSV with
year as a column.

One row per appeal. Carries filing date, court, classe, primary assunto,
relator, appeal type/nature, and last-decision summary.

Discovers bundles under two layouts to accommodate TSE renaming:
  2020: $DATA_DIR/TSE/2020/processos_eleitorais/recurso_eleitoral_2020.csv
  2024: $DATA_DIR/TSE/2024/recursos_eleitorais/recursos_eleitorais_2024.csv

Output: build/clean/recurso.csv
"""
import os
import re
from glob import glob

import path
import pandas as pd

import diarios.clean as clean


# REASONING: 2020 uses NR_RECURSO (process number), 2024 uses SQ_RECURSO
# (sequence id). Map both to a common column and keep both when available.
COLS = {
    'ANO_ELEICAO': 'elect_year',
    'DS_IDENTIFICACAO_RECURSO': 'identificacao',
    'NR_RECURSO': 'nr_recurso',
    'SQ_RECURSO': 'sq_recurso',
    'DT_AUTUACAO': 'data_autuacao',
    'DT_BAIXA': 'data_baixa',
    'NR_PROCESSO_ORIGEM': 'processo_origem',
    'SG_UF_TRIBUNAL_ORIGEM': 'tribunal_origem',
    'NR_INSTANCIA_ORIGEM': 'instancia_origem',
    'SG_UF_TRIBUNAL': 'tribunal',
    'NR_INSTANCIA': 'instancia',
    'DT_DISTRIBUICAO': 'data_distribuicao',
    'CD_TIPO_DISTRIBUICAO': 'cd_tipo_distribuicao',
    'DS_TIPO_DISTRIBUICAO': 'tipo_distribuicao',
    'CD_RELATOR': 'cd_relator',
    'NM_RELATOR': 'judge',
    'CD_TIPO_CARGO_RELATOR': 'cd_tipo_cargo_relator',
    'DS_TIPO_CARGO_RELATOR': 'judge_title',
    'CD_CLASSE': 'cd_classe',
    'SG_CLASSE': 'classe_sigla',
    'DS_CLASSE': 'classe',
    'CD_ASSUNTO_PRINCIPAL': 'assunto_code',
    'DS_ASSUNTO_PRINCIPAL': 'assunto',
    'DS_TIPO_RECURSO': 'tipo_recurso',
    'DS_NATUREZA_RECURSO': 'natureza_recurso',
    'ST_CONCLUSO': 'concluso',
    'QT_DECISOES': 'n_decisoes',
    'DT_ULTIMA_DECISAO': 'data_ultima_decisao',
    'DS_ULTIMA_DECISAO': 'ultima_decisao',
}

DATE_COLS = ['data_autuacao', 'data_baixa', 'data_distribuicao',
             'data_ultima_decisao']
INT_COLS = ['instancia', 'instancia_origem', 'n_decisoes',
            'cd_tipo_distribuicao', 'cd_relator', 'cd_tipo_cargo_relator',
            'cd_classe', 'assunto_code']
ST_COLS = ['concluso']


def clean_file(infile, year):
    # ASSUMES: NR_PROCESSO_ORIGEM is the 20-digit CNJ number — read as string
    # to avoid float precision loss.
    # REASONING: 2020 TSE CSVs have a trailing semicolon on data rows,
    # creating one more field than header columns. index_col=False prevents
    # pandas from misinterpreting the first data column as a row index.
    df = pd.read_csv(infile, encoding='latin1', sep=';',
                     dtype={'NR_PROCESSO_ORIGEM': str, 'NR_RECURSO': str,
                            'SQ_RECURSO': str},
                     low_memory=False, index_col=False)
    df = df.rename(columns=COLS)
    keep = [c for c in COLS.values() if c in df.columns]
    df = df.loc[:, keep].copy()
    df['year'] = int(year)

    for c in DATE_COLS:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], format='%d/%m/%Y', errors='coerce')

    for c in INT_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').astype('Int64')

    for c in ST_COLS:
        if c in df.columns:
            df[c] = (df[c] == 'S').astype(int)

    df = clean.clean_text_columns(
        df, exclude=['processo_origem', 'nr_recurso', 'sq_recurso',
                     'data_autuacao', 'data_baixa', 'data_distribuicao',
                     'data_ultima_decisao']
    )
    return df


def get_infiles():
    """Locate recurso CSVs across years.

    REASONING: TSE renamed both the directory and file prefix between years:
      2020: processos_eleitorais/recurso_eleitoral_{year}.csv
      2024: recursos_eleitorais/recursos_eleitorais_{year}.csv
    Glob both patterns and deduplicate by year.
    """
    patterns = [
        os.path.join(path.data_dir, 'TSE', '*', 'processos_eleitorais',
                     'recurso_eleitoral_*.csv'),
        os.path.join(path.data_dir, 'TSE', '*', 'recursos_eleitorais',
                     'recursos_eleitorais_*.csv'),
    ]
    by_year = {}
    for pattern in patterns:
        for f in glob(pattern):
            m = re.search(r'recurs\w+_(?:eleitoral(?:is)?_)?(\d{4})\.csv$', f)
            if not m:
                continue
            year = m.group(1)
            by_year.setdefault(year, f)
    return sorted(by_year.items())


if __name__ == '__main__':
    infiles = get_infiles()
    print(f'Found {len(infiles)} year bundles: {[y for y, _ in infiles]}')
    if not infiles:
        raise SystemExit('No recurso CSV files found under '
                         f'{path.data_dir}.')
    dfs = []
    for year, f in infiles:
        print(f'Processing {year}: {f}')
        dfs.append(clean_file(f, year))
    df = pd.concat(dfs, ignore_index=True)
    df.to_csv('build/clean/recurso.csv', index=False)

    with open('build/clean/recurso.txt', 'w') as f:
        f.write(f'Done — {len(df):,} rows across {df.year.nunique()} years\n')
        f.write(str(df.groupby('year').size()) + '\n')
