#! /usr/bin/env python3

bld = Builder(action='python3 $SOURCE')
env = Environment(BUILDERS={'Python': bld})

env.Python(
    target=['#build/clean/bem.txt'],
    source=['#source/clean/bem.py'],
)

env.Python(
    target=['#build/clean/receita.txt'],
    source=['#source/clean/receita.py'],
)

env.Python(
    target=['#build/clean/eleicao.csv'],
    source=['#source/clean/eleicao.py'],
)

env.Python(
    target=[
        '#build/clean/candidato.csv',
        '#build/clean/politico.csv',
    ],
    source=[
        '#source/clean/candidato_politico.py',
    ],
)

env.Python(
    target=[
        '#build/insert/politica.db',
    ],
    source=[
        '#source/insert/insert.py',
        '#source/raw/eleicoes.csv',
        '#build/clean/bem.txt',
        '#build/clean/receita.txt',
        '#build/clean/candidato.csv',
        '#build/clean/politico.csv',
    ],
)

env.Python(
    target=[
        '#build/insert/insert_mysql.txt',
    ],
    source=[
        '#source/insert/insert_mysql.py',
        '#source/raw/eleicoes.csv',
        '#build/clean/bem.txt',
        '#build/clean/receita.txt',
        '#build/clean/candidato.csv',
        '#build/clean/politico.csv',
    ],
)
