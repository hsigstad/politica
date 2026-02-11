import path
import diarios.database as db
import os
from glob import glob
from time import time

if __name__ == '__main__':
    t0 = time()

    DBNAME = "politica"

    db.insert(
        database=DBNAME,
        flavor="postgresql",
        table='eleicoes',
        columns=['id', 'year', 'round', 'electiondate', 'electiontype'],
        files=['source/raw/eleicoes.csv'],
    )

    db.insert(
        database=DBNAME,
        flavor="postgresql",   
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
        flavor="postgresql",   
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
        dtype_csv={'cpf': float},
        files=glob('build/clean/bem*')
    #    files=glob(
    #        os.path.join(
    #            path.data_dir,
    #            'TSE/*/bem_candidato/clean/*csv',
    #        )),
    )

    db.insert(
        database=DBNAME,
        flavor="postgresql",   
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
        dtype_csv={'cpf': float},
        files=glob('build/clean/receita*'),
        # files=glob(
        #     os.path.join(
        #         path.data_dir,
        #         'TSE/*/prestacao_contas_final/clean/*csv',
        #     )),
    )

    db.insert(
        database=DBNAME,
        flavor="postgresql",   
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
        dtype_csv={'cpf': int},
    )

    db.insert(
        database=DBNAME,
        flavor="postgresql",   
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
        dtype_csv={'cpf': int},
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
            'name': 'candidato_municipio_id'
        },
        {
            'table': 'candidato',
            'columns': ['cpf'],
            'name': 'candidato_cpf'
        },
        {
            'table': 'candidato',
            'columns': ['"SQ_CANDIDATO"'], # Must be in quotes to ensure kept upper case
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
            'name': 'candidato_office'
        },
        {
            'table': 'candidato',
            'columns': ['estado'],
            'name': 'candidato_estado'
        },
        {
            'table': 'bem',
            'columns': ['cpf'],
            'name': 'bem_cpf'
        },
        {
            'table': 'bem',
            'columns': ['"SQ_CANDIDATO"'],
            'name': 'bem_sq'
        },
        {
            'table': 'receita',
            'columns': ['cpf'],
            'name': 'receita_cpf'
        },
        {
            'table': 'receita',
            'columns': ['"SQ_CANDIDATO"'],
            'name': 'receita_sq'
        },
    ]

    for index in indices:
        db.create_index(database=DBNAME, flavor="postgresql", **index)

