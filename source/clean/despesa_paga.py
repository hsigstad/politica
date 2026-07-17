# INTENT: Build build/clean/despesa_paga.csv — candidate "paid" campaign
# expenditures, one row per despesa, tagged with the candidate's CPF and
# SQ_CANDIDATO recovered from the matching receita file.
# SOURCE: TSE prestação-de-contas BRASIL files (despesas_pagas_candidatos +
# receitas_candidatos) under $DATA_DIR/TSE/{year}/. Only the post-2018 schema
# carries the contratada/paga split, so this covers 2018 onward.
# ASSUMES: SQ_PRESTADOR_CONTAS is unique per (candidate) in the deduped receita,
# so the despesa→receita join is many-to-one (validated below).
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
    despesa_file = f"{finance_dir}/despesas_pagas_candidatos_{year}_BRASIL.csv"
    receita_file = f"{finance_dir}/receitas_candidatos_{year}_BRASIL.csv"
    despesa = pd.read_csv(despesa_file, sep=';', encoding='latin1')
    receita_cols = ['NR_CPF_CANDIDATO', 'SQ_CANDIDATO', 'SQ_PRESTADOR_CONTAS']
    receita = pd.read_csv(
        receita_file, sep=';', encoding='latin1',
        usecols=receita_cols
    ).drop_duplicates()
    despesa = despesa.merge(receita, on='SQ_PRESTADOR_CONTAS', validate='m:1', how='left')
    # Harmonize year column (ANO_ELEICAO in 2020, AA_ELEICAO in 2024)
    if 'AA_ELEICAO' in despesa.columns and 'ANO_ELEICAO' not in despesa.columns:
        despesa = despesa.rename(columns={'AA_ELEICAO': 'ANO_ELEICAO'})
    return despesa

# General cycles 2018/2022 added 2026-07-17; they share the post-2018 schema.
years = [2018, 2020, 2022, 2024]

df = pd.concat(map(clean_year, years))

def clean_value(value):
    return pd.to_numeric(value.str.replace(',', '.', regex=False))

df.to_csv('build/clean/despesa_paga.csv', index=False)

