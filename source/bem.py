import path
import pandas as pd
import re
from glob import glob

# TODO: RS dropping 30,000 duplicates


def clean_file(infile):
    print(infile)
    year = re.search('_([0-9]{4})_', infile).group(1)
    estado = re.search('([A-Z]{2}).(txt|csv)', infile).group(1)
    cand_year_estado = cand.loc[(cand.year == int(year))
                                & (cand.estado == estado)]
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
    on = 'SQ_CANDIDATO'
    df = df.merge(cand_year_estado, on=on, how='left', validate='m:1')
    outfile = infile.replace('.txt', '.csv')
    outfile = outfile.replace('bem_candidato/', 'bem_candidato/clean/')
    df.to_csv(outfile, index=False)
    return df


def get_cand():
    cand = pd.read_csv('build/clean/candidato.csv',
                       usecols=['year', 'estado', 'SQ_CANDIDATO', 'cpf'],
                       dtype={
                           'SQ_CANDIDATO': str,
                           'cpf': str
                       })
    for v in ['SQ_CANDIDATO', 'cpf']:
        cand[v] = cand[v].str.replace('\.0', '')
    return cand


cand = get_cand()

infiles1 = glob(
    os.path.join(path.local_data_dir, 'TSE/*/bem_candidato/bem_candidato*csv'))
infiles2 = glob(
    os.path.join(path.local_data_dir, 'TSE/*/bem_candidato/bem_candidato*txt'))
infiles = infiles1 + infiles2

df = pd.concat(map(clean_file, infiles))
