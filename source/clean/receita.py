import path
import pandas as pd
import re
import os
from glob import glob
from diarios.clean import clean_cpf


def clean_file(infile):
    print(infile)
    encoding = 'latin-1'
    sep = ';'
    df = pd.read_csv(infile,
                     encoding=encoding,
                     sep=sep,
                     dtype={
                         'Sequencial Candidato': str,
                         'CPF do candidato': str,
                         'CPF/CNPJ do doador': str,
                         'CD_NUM_CPF': str,
                         'NR_CPF_CANDIDATO': str,
                         'CD_CPF_CGC_DOA': str,
                     })
    year = re.search('/([0-9]{4})/', infile).group(1)
    if year == "2004":
        df = add_cpf_2004(df)
    cols = get_cols()
    df = df.rename(columns=cols)
    new_cols = list(set(df.columns).intersection(cols.values()))
    not_found = set(cols.values()).difference(df.columns)
    print('Not found:', not_found) # for checking
    df = df.loc[:, new_cols]
    if 'cpf' in df.columns:
        df['cpf'] = clean_cpf(df.cpf)
    df['valor_receita'] = df.valor_receita.str.replace(',', '.', regex=False)
    df['valor_receita'] = pd.to_numeric(df.valor_receita, errors='coerce')

    df['year'] = year
    outfile = f'build/clean/receita_{year}.csv'
    df.to_csv(outfile, index=False)
    return df


def get_cols():
    return {
        'SQ_CANDIDATO': 'SQ_CANDIDATO',
        'SEQUENCIAL_CANDIDATO': 'SQ_CANDIDATO',
        'SG_UF': 'estado',
        'NR_CANDIDATO': 'NUMERO_CAND',
        'NR_CAND': 'NUMERO_CAND',
        'NR_CPF_CANDIDATO': 'cpf',
        'CD_NUM_CPF': 'cpf',
        'NR_RECIBO_DOACAO': 'numero_recibo',
        'NR_DOCUMENTO_DOACAO': 'numero_do_documento',
        'NR_CPF_CNPJ_DOADOR': 'doador_documento',
        'CD_CPF_CNPJ_DOADOR': 'doador_documento',
        'CD_CPF_CGC_DOA': 'doador_documento',
        'NM_DOADOR': 'doador_nome',
        'NO_DOADOR': 'doador_nome',
        'NM_DOADOR_RFB': 'doador_nome_receita',
        'DS_CNAE_DOADOR': 'setor',
        'DT_RECEITA': 'data_receita',
        'VR_RECEITA': 'valor_receita',
        'DS_NATUREZA_RECEITA': 'tipo_receita',
        'DS_TITULO': 'tipo_receita',
        "RTRIM(LTRIM(DR.DS_TITULO))": 'tipo_receita',
        'DS_FONTE_RECEITA': 'fonte_recurso',
        'DS_ESPECIE_RECEITA': 'especie_recurso',
        'DS_ESP_RECURSO': 'especie_recurso',
        "DECODE(REC.TP_RECURSO,0,'EMESPÉCIE',1,'CHEQUE',2,'ESTIMADO','NÃOINFORMADO')": 'especie_recurso',
        'DS_RECEITA': 'descricao_receita',
        'Sequencial Candidato': 'SQ_CANDIDATO',
        'UF': 'estado',
        'SG_UE_SUPERIOR': 'estado',
        'SG_UE_SUP': 'estado',
        'Numero candidato': 'NUMERO_CAND',
        'CPF do candidato': 'cpf',
        'Numero Recibo Eleitoral': 'numero_recibo',
        'Numero do documento': 'numero_do_documento',
        'CPF/CNPJ do doador': 'doador_documento',
        'Nome do doador': 'doador_nome',
        'Nome do doador (Receita Federal)': 'doador_nome_receita',
        'Setor econômico do doador': 'setor',
        'Data da receita': 'data_receita',
        'Valor receita': 'valor_receita',
        'Tipo receita': 'tipo_receita',
        'Fonte recurso': 'fonte_recurso',
        'Especie recurso': 'especie_recurso',
        'Descricao da receita': 'descricao_receita',
        'NR_CAND': 'NUMERO_CAND',
        'SG_UE_SUP': 'estado',
        'RTRIM(LTRIM(DR.DS_TITULO))': 'tipo_receita',
        'CD_CPF_CGC_DOA': 'doador_documento',
    }


def add_cpf_2004(df):
    cand = pd.read_csv(
        os.path.join(path.data_dir, 'TSE/2004/consulta_cand/consulta_cand_2004_BRASIL.csv'),
        encoding='latin1',
        sep=';',
        dtype={'NR_CPF_CANDIDATO': str}
    ).query('DS_CARGO!="VICE-PREFEITO" & DS_DETALHE_SITUACAO_CAND=="DEFERIDO"')
    c2 = (
        cand[['NM_CANDIDATO', 'NR_CANDIDATO', 'SG_UE', 'NR_CPF_CANDIDATO']]
        .drop_duplicates()
        .drop_duplicates(['NM_CANDIDATO', 'NR_CANDIDATO', 'SG_UE']) # Drops a few
    )
    c2 = c2.rename(columns={'NR_CANDIDATO': 'NR_CAND', 'NM_CANDIDATO': 'NO_CAND'})
    out = df.merge(c2, on=['NR_CAND', 'SG_UE', 'NO_CAND'], how='left', validate="m:1")
    return out


if __name__ == '__main__':
    infiles1 = [ # Does not have CPF of candidato (only name). Need to write code to merge cpf in
        os.path.join(
            path.data_dir,
            'TSE/2004/prestacao_contas_final/Candidato/Receita/ReceitaCandidato.csv'
        )
    ]

    infiles = [
        f'{path.data_dir}/TSE/2004/prestacao_contas_final/Candidato/Receita/ReceitaCandidato.csv',
        f'{path.data_dir}/TSE/2008/prestacao_contas_final/receitas_candidatos_2008_brasil.csv',
        f'{path.data_dir}/TSE/2012/prestacao_contas_final/receitas_candidatos_2012_brasil.txt',
        f'{path.data_dir}/TSE/2016/prestacao_contas_final/receitas_candidatos_prestacao_contas_final_2016_brasil.txt',
        f'{path.data_dir}/TSE/2020/prestacao_contas_final/receitas_candidatos_2020_BRASIL.csv',
        f'{path.data_dir}/TSE/2024/prestacao_de_contas_eleitorais_candidatos/receitas_candidatos_2024_BRASIL.csv',
    ]

    df = pd.concat(map(clean_file, infiles))

    with open('build/clean/receita.txt', 'w') as f:
        f.write('Done')
