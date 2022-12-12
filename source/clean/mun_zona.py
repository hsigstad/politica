import path
import pandas as pd
import os
import re
from glob import glob


def get_mun_zona(infile):
    print(infile)
    year = re.search('[0-9]{4}', infile).group(0)
    cols = get_cols(year)
    if year in ['2018', '2020']:
        names = None
    else:
        names_file = os.path.join(
            os.path.dirname(infile),
            'variable-description.csv',
        )
        names = pd.read_csv(names_file, sep=';')['variable']
    df = pd.read_csv(infile,
                     sep=';',
                     names=names,
                     encoding='latin1',
                     usecols=cols.keys())
    df = df.drop_duplicates().rename(columns=cols)
    return df


def get_cols(year):
    if year in ['2018', '2020']:
        cols = {
            'SG_UF': 'estado',
            'ANO_ELEICAO': 'year',
            'NR_ZONA': 'zona',
            'NM_MUNICIPIO': 'municipio',
            'CD_MUNICIPIO': 'municipio_id'
        }
    else:
        cols = {
            'SIGLA_UF': 'estado',
            'ANO_ELEICAO': 'year',
            'NUMERO_ZONA': 'zona',
            'NOME_MUNICIPIO': 'municipio',
            'CODIGO_MUNICIPIO': 'municipio_id'
        }
    return cols


infiles = glob(
    os.path.join(
        path.data_dir,
        'elections',
        '*',
        'votacao_candidato_munzona',
        'votacao_candidato_munzona*',
    ))

df = pd.concat(map(get_mun_zona, infiles))
df = df.drop_duplicates()

print(df.sample(10))

df.to_csv('build/clean/mun_zona.csv', index=False)
