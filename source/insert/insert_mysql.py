import path
import diarios.database
from sqlalchemy import String
import pandas as pd

diarios.database.insert(
    database='politica',
    table='eleicoes',
    columns=['id', 'year', 'round', 'electiondate', 'electiontype'],
    files=['source/raw/eleicoes.csv'],
    flavor='mysql',
)

diarios.database.insert(
    database='politica',
    table='politico',
    dtype_csv={'cpf': str},
    dtype={'cpf': String(11)},
    columns=[
        'cpf',
        'politico',
        'race',
        'nationality',
        'gender',
        'birthdate',
        'birth_municipio_id',
        'birth_estado',
    ],
    files=['build/clean/politico.csv'],
    flavor='mysql',
)

diarios.database.insert(
    database='politica',
    table='candidato',
    dtype_csv={'cpf': str},
    dtype={'cpf': String(11)},
    columns=[
        'cpf',
        'estado',
        'municipio_id',
        'year',
        'office',
        'round',
        'votes',
        'elected',
        'electeddummy',
        'margin',
        'party',
        'coalition',
        'campaignexpenditure',
        'occupation',
        'education',
        'marital_status',
        'suplementar',
        'SQ_CANDIDATO',
        'NUMERO_CAND',
    ],
    files=['build/clean/candidato.csv'],
    flavor='mysql',
)

diarios.database.create_index(
    database='politica',
    table='politico',
    columns=['politico'],
    name='politico_fulltext',
    index_type='FULLTEXT',
    flavor='mysql',
)

diarios.database.create_index(
    database='politica',
    table='politico',
    columns=['politico'],
    name='politico',
    flavor='mysql',
)

diarios.database.create_index(
    database='politica',
    table='candidato',
    columns=['municipio_id'],
    name='mun_id',
    flavor='mysql',
)

diarios.database.create_index(
    database='politica',
    table='candidato',
    columns=['office'],
    name='office',
    flavor='mysql',
)
