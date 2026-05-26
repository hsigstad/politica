"""Clean TSE bulk electoral-process decision (decisão) table.

Reads `processos_eleitorais_decisoes_{year}.csv` bundles from
dadosabertos.tse.jus.br and writes one normalized CSV with year as a column.

One row per process-decision. Carries decision date, author, type, and
sequence number within the process.

Discovers bundles under two layouts:
  2020: $DATA_DIR/TSE/2020/processos_eleitorais/processos_eleitorais_decisoes_2020.csv
  2024: $DATA_DIR/TSE/2024/processos_eleitorais_decisoes/processos_eleitorais_decisoes_2024.csv

Output: build/clean/decisao.csv
"""
import os
import re
from glob import glob

import path
import pandas as pd

import diarios.clean as clean


# REASONING: 2020 has CD_TIPO_DECISAO (numeric code) that 2024 drops.
# Map both; missing columns are silently skipped.
COLS = {
    'ANO_ELEICAO': 'elect_year',
    'NR_PROCESSO': 'number',
    'SG_UF_TRIBUNAL_ORIGEM': 'tribunal_origem',
    'SQ_DECISAO': 'seq_decisao',
    'DT_DECISAO': 'data_decisao',
    'NM_AUTOR_DECISAO': 'autor_decisao',
    'CD_TIPO_DECISAO': 'cd_tipo_decisao',
    'DS_TIPO_DECISAO': 'tipo_decisao',
}

DATE_COLS = ['data_decisao']
INT_COLS = ['seq_decisao', 'cd_tipo_decisao']


def clean_file(infile, year):
    # ASSUMES: NR_PROCESSO is the 20-digit CNJ number — must read as string.
    # REASONING: 2020 TSE CSVs have a trailing semicolon on data rows,
    # creating one more field than header columns. index_col=False prevents
    # pandas from misinterpreting the first data column as a row index.
    df = pd.read_csv(infile, encoding='latin1', sep=';',
                     dtype={'NR_PROCESSO': str}, low_memory=False,
                     index_col=False)
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

    df = clean.clean_text_columns(df, exclude=['number', 'data_decisao'])
    return df


def get_infiles():
    """Locate processos_eleitorais_decisoes CSVs across years.

    REASONING: In 2020 the file lives inside processos_eleitorais/; in 2024
    it has its own top-level directory processos_eleitorais_decisoes/.
    """
    patterns = [
        os.path.join(path.data_dir, 'TSE', '*', 'processos_eleitorais',
                     'processos_eleitorais_decisoes_*.csv'),
        os.path.join(path.data_dir, 'TSE', '*', 'processos_eleitorais_decisoes',
                     'processos_eleitorais_decisoes_*.csv'),
    ]
    by_year = {}
    for pattern in patterns:
        for f in glob(pattern):
            m = re.search(r'decisoes_(\d{4})\.csv$', f)
            if not m:
                continue
            year = m.group(1)
            by_year.setdefault(year, f)
    return sorted(by_year.items())


if __name__ == '__main__':
    infiles = get_infiles()
    print(f'Found {len(infiles)} year bundles: {[y for y, _ in infiles]}')
    if not infiles:
        raise SystemExit('No processos_eleitorais_decisoes CSV files found '
                         f'under {path.data_dir}.')
    dfs = []
    for year, f in infiles:
        print(f'Processing {year}: {f}')
        dfs.append(clean_file(f, year))
    df = pd.concat(dfs, ignore_index=True)
    df.to_csv('build/clean/decisao.csv', index=False)

    with open('build/clean/decisao.txt', 'w') as f:
        f.write(f'Done — {len(df):,} rows across {df.year.nunique()} years\n')
        f.write(str(df.groupby('year').size()) + '\n')
