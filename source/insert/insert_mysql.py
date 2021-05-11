import path
import diarios.database as db
from sqlalchemy import String, BigInteger
import pandas as pd

db.insert(
    database='politica',
    table='eleicoes',
    columns=['year', 'round', 'electiondate', 'electiontype'],
    files=['source/raw/eleicoes.csv'],
    flavor='mysql',
)

db.insert(
    database='politica',
    table='politico',
    dtype_csv={'cpf': int},
    dtype={
        'cpf': BigInteger(),
        'politico': String(255)
    },
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

db.insert(
    database='politica',
    table='candidato',
    dtype_csv={'cpf': int},
    dtype={
        'cpf': BigInteger(),
        'office': String(75),
        'estado': String(2),
    },
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

db.create_index(
    database='politica',
    table='politico',
    columns=['politico'],
    name='politico',
    flavor='mysql',
)

db.create_index(
    database='politica',
    table='candidato',
    columns=['municipio_id'],
    name='mun_id',
    flavor='mysql',
)

db.create_index(
    database='politica',
    table='candidato',
    columns=['office'],
    name='office',
    flavor='mysql',
)

db.create_index(
    database='politica',
    table='candidato',
    columns=['cpf'],
    name='candidato_cpf',
    flavor='mysql',
)

db.create_index(
    database='politica',
    table='candidato',
    columns=['municipio_id'],
    name='municipio_id',
    flavor='mysql',
)

db.create_index(
    database='politica',
    table='candidato',
    columns=['estado'],
    name='estado',
    flavor='mysql',
)

db.create_index(
    database='politica',
    table='politico',
    columns=['cpf'],
    name='politico_cpf',
    flavor='mysql',
)

db.create_index(
    database='politica',
    table='politico',
    columns=['politico'],
    name='politico_fulltext',
    fulltext=True,
    flavor='mysql',
)

with open('build/insert/insert_mysql.txt', 'w') as f:
    f.write('Done')
