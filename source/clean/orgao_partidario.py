"""Clean TSE party-organ (órgão partidário) data.

INTENT: Normalize per-party CSVs of party organs and their members into a
single parquet with consistent column names, typed dates, and cleaned text.

Input:  $DATA_DIR/TSE/2022/orgao_partidario/orgao_partidario_*.csv
Output: build/clean/orgao_partidario.parquet
"""
import os
from glob import glob

import pandas as pd

import path
import diarios.clean as clean


COLS = {
    'SQ_ORGAO_PARTIDARIO': 'sq_orgao',
    'SG_PARTIDO': 'partido',
    'NR_PARTIDO': 'nr_partido',
    'NM_PARTIDO': 'nm_partido',
    'CD_TIPO_ORGAO_PARTIDARIO': 'cd_tipo_orgao',
    'NM_TIPO_ORGAO_PARTIDARIO': 'tipo_orgao',
    'CD_TIPO_ABRANGENCIA': 'cd_abrangencia',
    'DS_TIPO_ABRANGENCIA': 'abrangencia',
    'DT_INICIO_VIGENCIA_ORGAO': 'dt_inicio_orgao',
    'DT_FIM_VIGENCIA_ORGAO': 'dt_fim_orgao',
    'SG_UF': 'estado',
    'SG_UE': 'sg_ue',
    'NM_UE': 'nm_ue',
    'CD_MUNICIPIO': 'municipio_id',
    'NM_MUNICIPIO': 'municipio',
    'DS_ENDERECO_ORGAO': 'endereco',
    'NR_CEP_ORGAO': 'cep',
    'TX_EMAIL_ORGAO': 'email',
    'SQ_CARGO_MEMBRO': 'sq_cargo',
    'DS_CARGO_MEMBRO': 'cargo',
    'SQ_MEMBRO': 'sq_membro',
    'NM_MEMBRO': 'nome',
    'NR_TITULO_ELEITORAL_MEMBRO': 'titulo_eleitoral',
    'CD_GENERO': 'cd_genero',
    'DS_GENERO': 'genero',
    'DT_INICIO_EXERCICIO_MEMBRO': 'dt_inicio_membro',
    'DT_FIM_EXERCICIO_MEMBRO': 'dt_fim_membro',
    'DS_SITU_EXERC_MEMBRO': 'situacao_membro',
    'DS_SITU_EXERC_ORGAO_PARTIDARIO': 'situacao_orgao',
}

DATE_COLS = ['dt_inicio_orgao', 'dt_fim_orgao', 'dt_inicio_membro', 'dt_fim_membro']

# Phone/fax columns — dropped (noisy, not useful for analysis).
DROP_RAW = [
    'NR_FONE_FIXO_ORGAO', 'NR_FONE_CEL_ORGAO',
    'NR_FONE_COMERCIAL_ORGAO', 'NR_FAX_ORGAO',
    'DT_GERACAO', 'HH_GERACAO',
]


def clean_file(infile):
    # ASSUMES: latin1 encoding and semicolon separator (standard TSE bulk).
    df = pd.read_csv(infile, encoding='latin1', sep=';', low_memory=False,
                     dtype={'NR_TITULO_ELEITORAL_MEMBRO': str,
                            'CD_MUNICIPIO': str,
                            'NR_CEP_ORGAO': str})
    df = df.rename(columns=COLS)
    keep = [c for c in COLS.values() if c in df.columns]
    df = df.loc[:, keep].copy()

    for c in DATE_COLS:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], format='%d/%m/%Y', errors='coerce')

    # REASONING: -1 is TSE's sentinel for missing categorical codes.
    for c in ['cd_genero', 'cd_tipo_orgao', 'cd_abrangencia']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').astype('Int64')
            df.loc[df[c] == -1, c] = pd.NA

    # REASONING: sg_ue is sometimes numeric (e.g. zone codes) and sometimes
    # a state abbreviation — force to string so parquet doesn't choke on mixed types.
    for c in ['sg_ue', 'cep']:
        if c in df.columns:
            df[c] = df[c].astype(str).replace('-1', pd.NA).replace('nan', pd.NA)

    df = clean.clean_text_columns(
        df, exclude=['estado', 'titulo_eleitoral', 'cep', 'email',
                     'municipio_id'] + DATE_COLS
    )
    return df


def get_infiles():
    pattern = os.path.join(
        path.data_dir, 'TSE', '2022', 'orgao_partidario',
        'orgao_partidario_*.csv',
    )
    return sorted(glob(pattern))


if __name__ == '__main__':
    infiles = get_infiles()
    print(f'Found {len(infiles)} party files')
    if not infiles:
        raise SystemExit(
            f'No orgao_partidario CSVs found under {path.data_dir}/TSE/2022/')
    dfs = []
    for f in infiles:
        print(f'  {os.path.basename(f)}')
        dfs.append(clean_file(f))
    df = pd.concat(dfs, ignore_index=True)

    out = path.build_clean_dir / 'orgao_partidario.parquet'
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    print(f'Wrote {len(df):,} rows to {out}')
