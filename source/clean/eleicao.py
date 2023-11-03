import path
import pandas as pd
import os
import re
from glob import glob
from diarios.clean import clean_text


def read_csv(infile):
    year = int(re.search("_([0-9]{4})_", infile).group(1))
    df = pd.read_csv(infile, encoding="latin-1", sep=";")
    cols = get_cols()
    df = df.rename(columns=cols)
    new_cols = set(df.columns).intersection(cols.values())
    not_found = set(cols.values()).difference(df.columns)
    #print('Not found', year, ':', not_found) # for checking
    df = df.loc[:, new_cols]
    return df


def get_cols():
    return {
        "ANO_ELEICAO": "year",
        "NR_TURNO": "round",
        "NM_TIPO_ELEICAO": "tipo_eleicao",
        "SG_UF": "estado",
        "SG_UE": "ue",
        "TP_ABRANGENCIA": "tp_abrangencia",
        #'CD_MUNICIPIO': 'municipio_id',
        "DS_CARGO": "office",
        "QT_APTOS": "aptos",
        "QT_SECOES": "secoes",
        "QT_SECOES_PRINCIPAIS": "secoes", # need to verify this
        "QT_SECOES_AGREGADAS": "secoes_agregadas",
        "QT_APTOS_TOT": "aptos_tot",
        "QT_SECOES_TOT": "secoes_tot",
        "QT_TOTAL_SECOES": "secoes_tot",
        "QT_COMPARECIMENTO": "comparecimento",
        "QT_ABSTENCOES": "abstencoes",
        "ST_VOTO_EM_TRANSITO": "st_voto_em_transito",
        "QT_VOTOS_NOMINAIS": "votos_nominais",
        "QT_VOTOS_NOMINAIS_VALIDOS": "votos_nominais", # need to verify
        "QT_VOTOS_BRANCOS": "votos_brancos",
        "QT_VOTOS_NULOS": "votos_nulos",
        "QT_VOTOS_LEGENDA": "votos_legenda",
        "QT_VOTOS_LEGENDA_VALIDOS": "votos_legenda", # to verify       
        "QT_VOTOS_PENDENTES": "votos_pendentes",
        "QT_VOTOS_ANULADOS": "votos_anulados",
        "QT_VOTOS_NOMINAIS_ANULADOS": "votos_anulados", # to verify
    }


def clean(df):
    df["suplementar"] = df.tipo_eleicao.str.contains("(?i)suplementar")*1
    df = df.drop("tipo_eleicao", 1)
    df["office"] = clean_text(df.office)
    num_vars = set(df.columns) - {
        "office",
        "estado",
        "st_voto_em_transito",
        "tp_abrangencia",
        "ue",
    }
    for v in num_vars:
        df[v] = pd.to_numeric(df[v])
    return df


infiles1 = glob(
    os.path.join(path.data_dir, "TSE/*/detalhe_votacao_munzona/det*csv")
)
infiles2 = glob(
    os.path.join(path.data_dir, "TSE/*/detalhe_votacao_munzona/det*txt")
)
infiles = infiles1 + infiles2
df = pd.concat(map(read_csv, infiles))
df = clean(df)
el = (
    df.groupby(["year", "round", "estado", "office", "ue", "suplementar"])
    .agg(sum)
    .reset_index()
)
el["municipio_id"] = pd.to_numeric(el.ue, errors="coerce")
el.to_csv("build/clean/eleicao.csv", index=False)
