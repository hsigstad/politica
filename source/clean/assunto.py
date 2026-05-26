"""Clean TSE bulk electoral-process subject (assunto) table.

Reads `processos_eleitorais_assuntos_{year}.csv` bundles from
dadosabertos.tse.jus.br and writes one normalized CSV with year as a column.

One row per process-subject pair. A single process may have multiple assuntos;
the processo.py table carries only the *primary* assunto, while this table
carries all of them.

Discovers bundles under two layouts:
  2020: $DATA_DIR/TSE/2020/processos_eleitorais/processos_eleitorais_assuntos_2020.csv
  2024: $DATA_DIR/TSE/2024/processos_eleitorais_assuntos/processos_eleitorais_assuntos_2024.csv

Output: build/clean/assunto.csv
"""
import os
import re
from glob import glob

import path
import pandas as pd

import diarios.clean as clean


COLS = {
    'ANO_ELEICAO': 'elect_year',
    'NR_PROCESSO': 'number',
    'SG_UF_TRIBUNAL_ORIGEM': 'tribunal_origem',
    'CD_ASSUNTO': 'assunto_code',
    'DS_ASSUNTO': 'assunto',
}


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

    if 'assunto_code' in df.columns:
        df['assunto_code'] = pd.to_numeric(df['assunto_code'],
                                           errors='coerce').astype('Int64')

    df = clean.clean_text_columns(df, exclude=['number'])
    return df


def get_infiles():
    """Locate processos_eleitorais_assuntos CSVs across years.

    REASONING: In 2020 the file lives inside processos_eleitorais/; in 2024
    it has its own top-level directory processos_eleitorais_assuntos/.
    """
    patterns = [
        os.path.join(path.data_dir, 'TSE', '*', 'processos_eleitorais',
                     'processos_eleitorais_assuntos_*.csv'),
        os.path.join(path.data_dir, 'TSE', '*', 'processos_eleitorais_assuntos',
                     'processos_eleitorais_assuntos_*.csv'),
    ]
    by_year = {}
    for pattern in patterns:
        for f in glob(pattern):
            m = re.search(r'assuntos_(\d{4})\.csv$', f)
            if not m:
                continue
            year = m.group(1)
            by_year.setdefault(year, f)
    return sorted(by_year.items())


if __name__ == '__main__':
    infiles = get_infiles()
    print(f'Found {len(infiles)} year bundles: {[y for y, _ in infiles]}')
    if not infiles:
        raise SystemExit('No processos_eleitorais_assuntos CSV files found '
                         f'under {path.data_dir}.')
    dfs = []
    for year, f in infiles:
        print(f'Processing {year}: {f}')
        dfs.append(clean_file(f, year))
    df = pd.concat(dfs, ignore_index=True)
    df.to_csv('build/clean/assunto.csv', index=False)

    with open('build/clean/assunto.txt', 'w') as f:
        f.write(f'Done — {len(df):,} rows across {df.year.nunique()} years\n')
        f.write(str(df.groupby('year').size()) + '\n')
