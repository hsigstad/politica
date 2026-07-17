# INTENT: Harmonize the pre-2018 single-file TSE candidate expenditure
# ("despesa") records into one cleaned file per election year
# (build/clean/despesa_{year}.csv). This is the old-schema counterpart to
# despesa_contratada.py / despesa_paga.py, which only handle the post-2018
# contratada/paga split.
# SOURCE: TSE prestação-de-contas despesa files under $DATA_DIR/TSE/{year}/.
# Covers the general cycles 2002/2006/2010/2014 (the pre-2018 schema also exists
# for municipal 2004/2008/2012/2016 — add their paths to infiles to include).
# ASSUMES: the first /{4-digit}/ path component is the election year; amounts use
# a comma decimal separator; 2002/2006 carry no candidate CPF in-file (recovered
# via consulta_cand), while 2010/2014 expose "CPF do candidato" directly.
import path
import pandas as pd
import re
from glob import glob
from diarios.clean import clean_cpf
from receita import add_cpf_via_sq_ue


def clean_file(infile):
    # infile is a single path, or a list of same-year paths to concatenate
    # (2010 partitions despesa by candidato/{UF}/ with no consolidated file).
    files = [infile] if isinstance(infile, str) else list(infile)
    print(files[0] if len(files) == 1 else f'{files[0]} (+{len(files) - 1} more)')
    dtype = {
        'Sequencial Candidato': str,
        'CPF do candidato': str,
        'CPF/CNPJ do fornecedor': str,
        # 2002/2006 keys — strings so the (SQ, UE) CPF-recovery merge matches
        # consulta_cand (also read as str).
        'SEQUENCIAL_CANDIDATO': str,
        'CD_CPF_CGC': str,
        'NUMERO_CPF_CGC_FORNECEDOR': str,
    }
    df = pd.concat(
        [pd.read_csv(f, encoding='latin-1', sep=';', dtype=dtype) for f in files],
        ignore_index=True,
    )
    year = re.search('/([0-9]{4})/', files[0]).group(1)
    if year == "2002":
        df = add_cpf_via_sq_ue(df, 2002, 'SEQUENCIAL_CANDIDATO', 'SG_UF')
    elif year == "2006":
        df = add_cpf_via_sq_ue(df, 2006, 'SEQUENCIAL_CANDIDATO', 'UNIDADE_ELEITORAL_CANDIDATO')
    cols = get_cols()
    df = df.rename(columns=cols)
    new_cols = list(set(df.columns).intersection(cols.values()))
    print('Not found:', set(cols.values()).difference(df.columns))
    df = df.loc[:, new_cols]
    if 'cpf' in df.columns:
        df['cpf'] = clean_cpf(df.cpf)
    df['valor_despesa'] = df.valor_despesa.str.replace(',', '.', regex=False)
    df['valor_despesa'] = pd.to_numeric(df.valor_despesa, errors='coerce')

    df['year'] = year
    outfile = f'build/clean/despesa_{year}.csv'
    df.to_csv(outfile, index=False)
    return df


def get_cols():
    return {
        # candidate sequence / electoral unit / number
        'SEQUENCIAL_CANDIDATO': 'SQ_CANDIDATO',
        'Sequencial Candidato': 'SQ_CANDIDATO',
        'SG_UF': 'estado',
        'UF': 'estado',
        'UNIDADE_ELEITORAL_CANDIDATO': 'estado',
        'NR_CAND': 'NUMERO_CAND',
        'NUMERO_CANDIDATO': 'NUMERO_CAND',
        'Número candidato': 'NUMERO_CAND',
        # candidate CPF (2010/2014 in-file; 2002/2006 recovered via merge)
        'CPF do candidato': 'cpf',
        'NR_CPF_CANDIDATO': 'cpf',
        # amount
        'VR_DESPESA': 'valor_despesa',
        'VALOR_DESPESA': 'valor_despesa',
        'Valor despesa': 'valor_despesa',
        # date
        'DT_DOC_DESP': 'data_despesa',
        'DATA_DESPESA': 'data_despesa',
        'Data da despesa': 'data_despesa',
        # expense type
        'DS_TITULO': 'tipo_despesa',
        'TIPO_DESPESA': 'tipo_despesa',
        'Tipo despesa': 'tipo_despesa',
        # supplier (fornecedor)
        'CD_CPF_CGC': 'fornecedor_documento',
        'NUMERO_CPF_CGC_FORNECEDOR': 'fornecedor_documento',
        'CPF/CNPJ do fornecedor': 'fornecedor_documento',
        'NO_FOR': 'fornecedor_nome',
        'NOME_FORNECEDOR': 'fornecedor_nome',
        'Nome do fornecedor': 'fornecedor_nome',
        'Nome do fornecedor (Receita Federal)': 'fornecedor_nome_receita',
        'Setor econômico do fornecedor': 'setor',
        # document / resource
        'NUMERO_DOCUMENTO': 'numero_do_documento',
        'Número do documento': 'numero_do_documento',
        'Fonte recurso': 'fonte_recurso',
        'Espécie recurso': 'especie_recurso',
        'Descriçao da despesa': 'descricao_despesa',
    }


if __name__ == '__main__':
    infiles = [
        # General cycles (pre-2018 single-despesa-file schema). 2002/2006 lack
        # candidate CPF; 2010 partitions by UF (concatenate all); 2014 has a
        # national ..._brasil.txt roll-up.
        f'{path.data_dir}/TSE/2002/prestacao_contas/2002/Candidato/Despesa/DespesaCandidato.csv',
        f'{path.data_dir}/TSE/2006/prestacao_contas/2006/Candidato/Despesa/DespesaCandidato.csv',
        sorted(glob(f'{path.data_dir}/TSE/2010/prestacao_contas/candidato/*/DespesasCandidatos.txt')),
        f'{path.data_dir}/TSE/2014/prestacao_contas/despesas_candidatos_2014_brasil.txt',
    ]
    for infile in infiles:
        clean_file(infile)

    with open('build/clean/despesa.txt', 'w') as f:
        f.write('Done')
