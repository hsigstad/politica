import appendpath
import diarios.database as db

DBNAME = 'build/insert/politica.db'

db.insert(database=DBNAME,
          table='eleicao',
          columns=['id', 'year', 'round', 'electiondate', 'electiontype'],
          files=['source/eleicao.csv'])

db.insert(database=DBNAME,
          table='politico',
          columns=[
              'cpf', 'politico', 'race', 'nationality', 'gender', 'birthdate',
              'birth_municipio_id', 'birth_estado'
          ],
          files=['build/clean/politico.csv'])

db.insert(database=DBNAME,
          table='candidato',
          columns['cpf', 'estado', 'municipio_id', 'year', 'office', 'round',
                  'votes', 'elected', 'electeddummy', 'margin', 'party',
                  'coalition', 'campaignexpenditure', 'occupation',
                  'education', 'marital_status', 'suplementar', 'SQ_CANDIDATO',
                  'NUMERO_CAND'],
          files=['build/clean/candidato.csv'])

indices = [{
    'table': 'politico',
    'columns': ['politico'],
    'name': 'politico_ix'
}, {
    'table': 'candidato',
    'columns': ['municipio_id'],
    'name': 'parte_mov_id'
}, {
    'table': 'candidato',
    'columns': ['cpf'],
    'name': 'candidato_cpf'
}, {
    'table': 'politico',
    'columns': ['cpf'],
    'name': 'politico_cpf'
}, {
    'table': 'candidato',
    'columns': ['office'],
    'name': 'office'
}]

for index in indices:
    db.create_index(database=DBNAME, **index)
