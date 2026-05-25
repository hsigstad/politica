import path
import pandas as pd
import os
from glob import glob


def get_finance_dir(year):
    new_dir = f"{path.data_dir}/TSE/{year}/prestacao_de_contas_eleitorais_candidatos"
    old_dir = f"{path.data_dir}/TSE/{year}/prestacao_contas_final"
    return new_dir if os.path.isdir(new_dir) else old_dir


def clean_year(year):
    print(year)
    finance_dir = get_finance_dir(year)
    despesa_file = f"{finance_dir}/despesas_contratadas_candidatos_{year}_BRASIL.csv"
    receita_file = f"{finance_dir}/receitas_candidatos_{year}_BRASIL.csv"
    despesa = pd.read_csv(despesa_file, sep=';', encoding='latin1')
    receita_cols = ['NR_CPF_CANDIDATO', 'SQ_CANDIDATO', 'SQ_PRESTADOR_CONTAS']
    receita = pd.read_csv(
        receita_file, sep=';', encoding='latin1',
        usecols=receita_cols
    ).drop_duplicates()
    despesa = despesa.merge(receita, on='SQ_PRESTADOR_CONTAS', validate='m:1', how='left')
    return despesa

years = [2020, 2024]

df = pd.concat(map(clean_year, years))

def clean_value(value):
    return pd.to_numeric(value.str.replace(',', '.', regex=False))

df.to_csv('build/clean/despesa_contratada.csv', index=False)

