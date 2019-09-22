import pandas as pd

pol = pd.read_csv('../build/clean/politico.csv')
pol = pol.sample(1000)
cand = pd.read_csv('../build/clean/candidato.csv')
cand = pd.merge(
    cand, pol.loc[:, ('cpf')], on='cpf'
)
cand.to_csv('../build/clean/candidato_short.csv')
pol.to_csv('../build/clean/politico_short.csv')

