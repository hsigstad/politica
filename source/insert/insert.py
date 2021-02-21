import path
import diarios.database as db
import os
from glob import glob
from sqlalchemy.types import String

DBNAME = 'build/insert/politica.db'

db.insert(
    database=DBNAME,
    table='eleicoes',
    columns=['id', 'year', 'round', 'electiondate', 'electiontype'],
    files=['source/raw/eleicoes.csv'],
)

db.insert(
    database=DBNAME,
    table='eleicao',
    columns=[
        'year',
        'round',
        'estado',
        'office',
        'ue',
        'aptos',
        'secoes',
        'secoes_agregadas',
        'aptos_tot',
        'secoes_tot',
        'comparecimento',
        'abstencoes',
        'votos_nominais',
        'votos_brancos',
        'votos_nulos',
        'votos_legenda',
        'votos_pendentes',
        'votos_anulados',
        'votos_anulados_apu_sep',
        'suplementar',
        'municipio_id',
    ],
    files=['build/clean/eleicao.csv'],
)

db.insert(
    database=DBNAME,
    table='bem',
    columns=[
        'SQ_CANDIDATO',
        'cpf',
        'estado',
        'year',
        'tipo_bem',
        'valor_bem',
        'descricao_bem',
    ],
    files=glob(
        os.path.join(path.local_data_dir, 'TSE/*/bem_candidato/clean/*csv')),
    dtype_csv={'cpf': str},
)

db.insert(
    database=DBNAME,
    table='receita',
    columns=[
        'SQ_CANDIDATO',
        'cpf',
        'year',
        'estado',
        'numero_recibo',
        'numero_do_documento',
        'doador_documento',
        'doador_nome',
        'doador_nome_receita',
        'setor',
        'data_receita',
        'valor_receita',
        'tipo_receita',
        'fonte_recurso',
        'especie_recurso',
        'descricao_receita',
    ],
    files=glob(
        os.path.join(path.local_data_dir,
                     'TSE/*/prestacao_contas_final/clean/*csv')),
    dtype_csv={'cpf': str},
)

db.insert(
    database=DBNAME,
    table='politico',
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
)

db.insert(
    database=DBNAME,
    table='candidato',
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
)

indices = [
    {
        'table': 'politico',
        'columns': ['politico'],
        'name': 'politico_ix'
    },
    {
        'table': 'candidato',
        'columns': ['municipio_id'],
        'name': 'parte_mov_id'
    },
    {
        'table': 'candidato',
        'columns': ['cpf'],
        'name': 'candidato_cpf'
    },
    {
        'table': 'candidato',
        'columns': ['SQ_CANDIDATO'],
        'name': 'candidato_sq'
    },
    {
        'table': 'politico',
        'columns': ['cpf'],
        'name': 'politico_cpf'
    },
    {
        'table': 'candidato',
        'columns': ['office'],
        'name': 'office'
    },
    {
        'table': 'candidato',
        'columns': ['estado'],
        'name': 'estado'
    },
    {
        'table': 'bem',
        'columns': ['cpf'],
        'name': 'bem_cpf'
    },
    {
        'table': 'bem',
        'columns': ['SQ_CANDIDATO'],
        'name': 'bem_sq'
    },
    {
        'table': 'receita',
        'columns': ['cpf'],
        'name': 'receita_cpf'
    },
    {
        'table': 'receita',
        'columns': ['SQ_CANDIDATO'],
        'name': 'receita_sq'
    },
]

for index in indices:
    db.create_index(database=DBNAME, **index)
