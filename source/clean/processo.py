"""Clean TSE bulk electoral-process metadata.

Reads `processo_eleitoral_{year}.csv` bundles from dadosabertos.tse.jus.br
(dataset `processual-{year}`) and writes one normalized CSV with year as a
column.

The file is canonical TSE bulk processo data — one row per process per
instance. It carries filing date, court, classe, primary assunto, relator,
etc., but does NOT carry parties (plaintiff/defendant); those come from the
diários parse in a separate TRE-diários pipeline.

Discovers bundles under two locations to accommodate both the politica
convention and ad-hoc unpacking:
  - $DATA_DIR/TSE/{year}/processos_eleitorais/processo_eleitoral_{year}.csv
  - $DATA_DIR/processo_eleitoral_{year}/processo_eleitoral_{year}.csv

Output: build/clean/processo.csv (one row per year-process-instance).
"""
import os
import re
from glob import glob

import path
import pandas as pd

import diarios.clean as clean


# Column map: superset across years. Pandas silently drops missing keys, so
# years that lack a column (e.g. 2020 has no CD_ASSUNTO_PRINCIPAL) just skip
# it.
COLS = {
    'NR_PROCESSO': 'number',
    'ANO_ELEICAO': 'elect_year',
    'DT_AUTUACAO': 'data_autuacao',
    'DT_DISTRIBUICAO': 'data_distribuicao',
    'DT_BAIXA': 'data_baixa',
    'SG_UF_TRIBUNAL': 'tribunal',
    'SG_UF_TRIBUNAL_ORIGEM': 'tribunal_origem',
    'NR_INSTANCIA': 'instancia',
    'NR_INSTANCIA_ORIGEM': 'instancia_origem',
    'SG_CLASSE': 'classe_sigla',
    'DS_CLASSE': 'classe',
    'CD_ASSUNTO_PRINCIPAL': 'assunto_code',
    'DS_ASSUNTO_PRINCIPAL': 'assunto',
    'NM_RELATOR': 'judge',
    'DS_TIPO_CARGO_RELATOR': 'judge_title',
    'DS_TIPO_DISTRIBUICAO': 'tipo_distribuicao',
    'QT_DECISOES': 'n_decisoes',
    'ST_CONCLUSO': 'concluso',
    'ST_EM_PAUTA': 'em_pauta',
    'ST_SOBRESTADO': 'sobrestado',
    'ST_PEDIDO_VISTA': 'pedido_vista',
    'ST_CARGA_VISTA_MPE': 'carga_vista_mpe',
    'ST_RECURSAL': 'recursal',
    'ST_REMESSA_SUPERIOR': 'remessa_superior',
}

DATE_COLS = ['data_autuacao', 'data_distribuicao', 'data_baixa']
ST_COLS = [
    'concluso', 'em_pauta', 'sobrestado', 'pedido_vista',
    'carga_vista_mpe', 'recursal', 'remessa_superior',
]


def clean_file(infile, year):
    # ASSUMES: NR_PROCESSO is the 20-digit CNJ number — must read as string
    # so float precision loss does not corrupt the join key.
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
    if 'instancia' in df.columns:
        df['instancia'] = pd.to_numeric(df['instancia'], errors='coerce').astype('Int64')
    if 'instancia_origem' in df.columns:
        df['instancia_origem'] = pd.to_numeric(df['instancia_origem'], errors='coerce').astype('Int64')
    if 'n_decisoes' in df.columns:
        df['n_decisoes'] = pd.to_numeric(df['n_decisoes'], errors='coerce').astype('Int64')

    # ST_* flags arrive as "S"/"N" strings — coerce to 0/1.
    for c in ST_COLS:
        if c in df.columns:
            df[c] = (df[c] == 'S').astype(int)

    df = clean.clean_text_columns(
        df, exclude=['number', 'data_autuacao', 'data_distribuicao', 'data_baixa']
    )
    return df


def get_infiles():
    """Locate one processo_eleitoral_{year}.csv per available year.

    REASONING: TSE bundles get unpacked in different layouts across local
    setups. Scan two known patterns; if a year appears in both, prefer the
    politica-convention path (TSE/{year}/processos_eleitorais/).
    """
    # TSE renamed the subdir between years: 2020 = "processos_eleitorais",
    # 2024 = "processo_eleitoral". Glob both.
    patterns = [
        os.path.join(path.data_dir, 'TSE', '*', 'processos_eleitorais',
                     'processo_eleitoral_*.csv'),
        os.path.join(path.data_dir, 'TSE', '*', 'processo_eleitoral',
                     'processo_eleitoral_*.csv'),
        os.path.join(path.data_dir, 'processo_eleitoral_*',
                     'processo_eleitoral_*.csv'),
    ]
    by_year = {}
    for pattern in patterns:
        for f in glob(pattern):
            m = re.search(r'processo_eleitoral_(\d{4})\.csv$', f)
            if not m:
                continue
            year = m.group(1)
            by_year.setdefault(year, f)  # first hit wins → convention path
    return sorted(by_year.items())


if __name__ == '__main__':
    infiles = get_infiles()
    print(f'Found {len(infiles)} year bundles: {[y for y, _ in infiles]}')
    if not infiles:
        raise SystemExit('No processo_eleitoral_*.csv files found under '
                         f'{path.data_dir}.')
    dfs = []
    for year, f in infiles:
        print(f'Processing {year}: {f}')
        dfs.append(clean_file(f, year))
    df = pd.concat(dfs, ignore_index=True)
    df.to_csv('build/clean/processo.csv', index=False)

    with open('build/clean/processo.txt', 'w') as f:
        f.write(f'Done — {len(df):,} rows across {df.year.nunique()} years\n')
        f.write(str(df.groupby('year').size()) + '\n')
