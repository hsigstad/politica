import path
import pandas as pd
import os
from glob import glob
import diarios.clean as clean


def clean_file(infile):
    print(infile)
    df = pd.read_csv(infile, encoding='latin1', sep=';')
    cols = {
        'AA_ELEICAO': 'year',
        'ANO_ELEICAO': 'year',
        'NR_TURNO': 'round',
        'SG_UF': 'estado',
        'CD_MUNICIPIO': 'municipio_id',
        'NM_MUNICIPIO': 'municipio',
        'NR_ZONA': 'zona',
        'NR_SECAO': 'secao',
        'NR_LOCAL_VOTACAO': 'local_votacao_id',
        'NM_LOCAL_VOTACAO': 'local_votacao',
        'DS_TIPO_LOCAL': 'tipo_local',
        'DS_ENDERECO': 'endereco',
        'NM_BAIRRO': 'bairro',
        'NR_CEP': 'cep',
        'NR_LATITUDE': 'latitude',
        'NR_LONGITUDE': 'longitude',
        'DS_SITU_LOCAL_VOTACAO': 'situacao_local',
        'DS_SITU_SECAO_ACESSIBILIDADE': 'acessibilidade',
        'QT_ELEITOR_SECAO': 'qt_eleitores_secao',
        'QT_ELEITOR_ELEICAO_MUNICIPAL': 'qt_eleitores_municipal',
    }
    df = df.rename(columns=cols)
    new_cols = list(set(df.columns).intersection(cols.values()))
    df = df.loc[:, new_cols]
    df = clean.clean_text_columns(df, exclude=['estado', 'cep'])
    df['ibge7'] = clean.transform(df['municipio_id'], 'municipio_id', 'ibge7')
    return df


if __name__ == '__main__':
    infiles = glob(
        os.path.join(path.data_dir,
                     'TSE/*/eleitorado_local_votacao/eleitorado_local_votacao_*.csv'))
    df = pd.concat(map(clean_file, infiles))
    df.to_csv('build/clean/eleitorado_local_votacao.csv', index=False)

    with open('build/clean/eleitorado_local_votacao.txt', 'w') as f:
        f.write('Done')
