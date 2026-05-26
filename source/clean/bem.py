import path
import pandas as pd
import re
import os
from glob import glob
from diarios.clean import clean_cpf

# TODO: RS dropping 30,000 duplicates


def clean_file(infile):
    print(infile)
    year = re.search('_([0-9]{4})_', infile).group(1)
    estado = re.search('([A-Z]{2}).(txt|csv)', infile).group(1)
    cand_year_estado = cand.loc[(cand.year == int(year))
                                & (cand.estado == estado),
                                ('SQ_CANDIDATO', 'cpf')]
    base_dir = os.path.dirname(infile)
    try:
        names = pd.read_csv(os.path.join(base_dir, 'variables.csv')).variable
    except FileNotFoundError:
        names = None
    l1 = len(cand_year_estado)
    cand_year_estado = cand_year_estado.drop_duplicates('SQ_CANDIDATO')
    l2 = len(cand_year_estado)
    if l2 < l1:
        print('Dropped', l1 - l2, 'duplicates')
    encoding = 'latin-1'
    sep = ';'
    df = pd.read_csv(infile,
                     encoding=encoding,
                     sep=sep,
                     names=names,
                     dtype={'SQ_CANDIDATO': str})
    cols = get_cols()
    df = df.rename(columns=cols).loc[:, list(set(cols.values()))]
    if df.valor_bem.dtype == object:
        df['valor_bem'] = df.valor_bem.str.replace(',', '.', regex=True)
        df['valor_bem'] = pd.to_numeric(df.valor_bem, errors='coerce')
    on = 'SQ_CANDIDATO'
    df = df.merge(cand_year_estado, on=on, how='left', validate='m:1')
    outfile = os.path.basename(infile).replace('.txt', '.csv')
    outfile = 'build/clean/{}'.format(outfile)
    df.to_csv(outfile, index=False)
    return df


def get_cols():
    cols = {
        'SQ_CANDIDATO': 'SQ_CANDIDATO',
        #'NR_ORDEM_CANDIDATO': 'NR_ORDEM_CANDIDATO', only for 2016
        'ANO_ELEICAO': 'year',
        'SG_UF': 'estado',
        'SIGLA_UF': 'estado',
        'DS_TIPO_BEM_CANDIDATO': 'tipo_bem',
        'DS_BEM_CANDIDATO': 'descricao_bem',
        'DETALHE_BEM': 'descricao_bem',
        'VR_BEM_CANDIDATO': 'valor_bem',
        'VALOR_BEM': 'valor_bem',
    }
    return cols


def get_cand():
    cand = pd.read_csv('build/clean/candidato.csv',
                       usecols=['year', 'estado', 'SQ_CANDIDATO', 'cpf'],
                       dtype={'SQ_CANDIDATO': str})
    cand['SQ_CANDIDATO'] = cand.SQ_CANDIDATO.str.replace('.0', '', regex=False)
    cand['cpf'] = clean_cpf(cand.cpf)
    return cand


cand = get_cand()

infiles1 = glob(
    os.path.join(path.data_dir,
                 'TSE/2008/bem_candidato/bem_candidato*txt'))
infiles2 = glob(
    os.path.join(path.data_dir,
                 'TSE/2012/bem_candidato/bem_candidato*txt'))
infiles3 = glob(
    os.path.join(path.data_dir,
                 'TSE/2016/bem_candidato/bem_candidato*'))
infiles4 = glob(
    os.path.join(path.data_dir,
                 'TSE/2020/bem_candidato/bem_candidato*'))
infiles5 = glob(
    os.path.join(path.data_dir,
                 'TSE/2024/bem_candidato/bem_candidato*'))

infiles = infiles1 + infiles2 + infiles3 + infiles4 + infiles5
df = pd.concat(map(clean_file, infiles))

with open('build/clean/bem.txt', 'w') as f:
    f.write('Done')
