import path
import pandas as pd
import os
from glob import glob
import diarios.clean as clean


TXT_COLUMNS = [
    'DT_GERACAO', 'HH_GERACAO', 'CD_ELEICAO', 'DS_ELEICAO',
    'ANO_ELEICAO', 'SG_UF', 'SG_UE', 'SQ_CANDIDATO', 'DS_MOTIVO_CASSACAO',
]


def clean_file(infile):
    print(infile)
    try:
        if infile.endswith('.txt'):
            df = pd.read_csv(infile, encoding='latin1', sep=';',
                             header=None, names=TXT_COLUMNS)
        else:
            df = pd.read_csv(infile, encoding='latin1', sep=';')
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    cols = {
        'ANO_ELEICAO': 'year',
        'CD_ELEICAO': 'cd_eleicao',
        'DS_ELEICAO': 'eleicao',
        'SG_UF': 'estado',
        'SG_UE': 'distrito',
        'NM_UE': 'distrito_nome',
        'SQ_CANDIDATO': 'SQ_CANDIDATO',
        'NR_PROCESSO': 'nr_processo',
        'DS_TP_MOTIVO': 'tipo_motivo',
        'DS_MOTIVO': 'motivo',
        # 2018/2020 format (single motivo column)
        'DS_MOTIVO_CASSACAO': 'motivo',
    }
    df = df.rename(columns=cols)
    new_cols = list(set(df.columns).intersection(cols.values()))
    df = df.loc[:, new_cols]
    df = clean.clean_text_columns(df, exclude=['estado', 'nr_processo'])
    return df


def get_infiles():
    """Get one national file per year. Use BRASIL/BR aggregates where available,
    fall back to per-state files otherwise (e.g. 2016 txt)."""
    all_files = (
        glob(os.path.join(path.data_dir, 'TSE/*/motivo_cassacao/motivo_cassacao_*.*'))
    )
    # Group by year
    import re
    by_year = {}
    for f in all_files:
        if f.endswith('.pdf'):
            continue
        m = re.search(r'/TSE/(\d{4})/', f)
        if not m:
            continue
        year = m.group(1)
        by_year.setdefault(year, []).append(f)
    infiles = []
    for year, files in sorted(by_year.items()):
        national = [f for f in files if '_BRASIL.' in f or '_BR.' in f]
        # Use national file if it exists and is non-empty
        national = [f for f in national if os.path.getsize(f) > 0]
        if national:
            infiles.extend(national)
        else:
            # Use per-state files, excluding leiame etc
            state_files = [f for f in files if re.search(r'_[A-Z]{2}\.(csv|txt)$', f)]
            infiles.extend(state_files)
    return sorted(infiles)


if __name__ == '__main__':
    infiles = get_infiles()
    print(f'Processing {len(infiles)} files')
    df = pd.concat(map(clean_file, infiles))
    df.to_csv('build/clean/motivo_cassacao.csv', index=False)

    with open('build/clean/motivo_cassacao.txt', 'w') as f:
        f.write('Done')
