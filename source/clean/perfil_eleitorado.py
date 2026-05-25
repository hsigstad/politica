import path
import pandas as pd
import os
from glob import glob
import diarios.clean as clean


def clean_file(infile):
    print(infile)
    df = pd.read_csv(infile, encoding='latin1', sep=';')
    cols = {
        'ANO_ELEICAO': 'year',
        'SG_UF': 'estado',
        'CD_MUNICIPIO': 'municipio_id',
        'NM_MUNICIPIO': 'municipio',
        'NR_ZONA': 'zona',
        'CD_GENERO': 'cd_genero',
        'DS_GENERO': 'genero',
        'CD_ESTADO_CIVIL': 'cd_estado_civil',
        'DS_ESTADO_CIVIL': 'estado_civil',
        'CD_FAIXA_ETARIA': 'cd_faixa_etaria',
        'DS_FAIXA_ETARIA': 'faixa_etaria',
        'CD_GRAU_ESCOLARIDADE': 'cd_escolaridade',
        'DS_GRAU_ESCOLARIDADE': 'escolaridade',
        'CD_RACA_COR': 'cd_raca',
        'DS_RACA_COR': 'raca',
        'QT_ELEITORES_PERFIL': 'qt_eleitores',
        'QT_ELEITORES_BIOMETRIA': 'qt_eleitores_biometria',
        'QT_ELEITORES_DEFICIENCIA': 'qt_eleitores_deficiencia',
        'QT_ELEITORES_INC_NM_SOCIAL': 'qt_eleitores_nome_social',
    }
    df = df.rename(columns=cols)
    new_cols = list(set(df.columns).intersection(cols.values()))
    df = df.loc[:, new_cols]
    df = clean.clean_text_columns(df, exclude=['estado'])
    df['ibge7'] = clean.transform(df['municipio_id'], 'municipio_id', 'ibge7')
    return df


if __name__ == '__main__':
    infiles = glob(
        os.path.join(path.data_dir, 'TSE/*/perfil_eleitorado/perfil_eleitorado_*.csv'))
    df = pd.concat(map(clean_file, infiles))
    df.to_csv('build/clean/perfil_eleitorado.csv', index=False)

    with open('build/clean/perfil_eleitorado.txt', 'w') as f:
        f.write('Done')
