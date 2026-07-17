# INTENT: Harmonize the pre-2018 single-file TSE candidate expenditure
# ("despesa") records into one cleaned file per election year
# (build/clean/despesa_{year}.csv). This is the old-schema counterpart to
# despesa_contratada.py / despesa_paga.py, which only handle the post-2018
# contratada/paga split.
# SOURCE: TSE prestação-de-contas despesa files under $DATA_DIR/TSE/{year}/.
# Covers all pre-2018 cycles: general 2002/2006/2010/2014 and municipal
# 2004/2008/2012/2016.
# ASSUMES: the first /{4-digit}/ path component is the election year; amounts use
# a comma decimal separator; 2002/2006 carry no candidate CPF in-file (recovered
# via consulta_cand), while 2010/2014 expose "CPF do candidato" directly.
import path
import pandas as pd
import re
from glob import glob
from diarios.clean import clean_cpf
from receita import add_cpf_via_sq_ue, add_cpf_2004


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
        'CD_CPF_CNPJ_FORNECEDOR': str,
    }
    df = pd.concat(
        [pd.read_csv(f, encoding='latin-1', sep=';', dtype=dtype) for f in files],
        ignore_index=True,
    )
    year = re.search('/([0-9]{4})/', files[0]).group(1)
    # Guard against header-only source files (e.g. the 2016 despesa snapshot is
    # empty on disk) so we never silently write a 0-row output.
    if len(df) == 0:
        print(f'  SKIP {year}: source has no data rows')
        return None
    if year == "2002":
        df = add_cpf_via_sq_ue(df, 2002, 'SEQUENCIAL_CANDIDATO', 'SG_UF')
    elif year == "2004":
        # 2004 despesa has no candidate CPF and no SQ; use the same name-based
        # (NR_CAND, SG_UE, NO_CAND) recovery as receita 2004.
        df = add_cpf_2004(df)
    elif year == "2006":
        df = add_cpf_via_sq_ue(df, 2006, 'SEQUENCIAL_CANDIDATO', 'UNIDADE_ELEITORAL_CANDIDATO')
    elif year == "2008":
        df = add_cpf_via_sq_ue(df, 2008, 'SEQUENCIAL_CANDIDATO', 'SG_UE')
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
        # 2004/2008 carry the "superior" electoral unit as the state.
        'SG_UE_SUP': 'estado',
        'SG_UE_SUPERIOR': 'estado',
        'NR_CAND': 'NUMERO_CAND',
        'NR_CANDIDATO': 'NUMERO_CAND',
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
        'DT_DESPESA': 'data_despesa',
        'DATA_DESPESA': 'data_despesa',
        'Data da despesa': 'data_despesa',
        # expense type
        'DS_TITULO': 'tipo_despesa',
        'RTRIM(LTRIM(DR.DS_TITULO))': 'tipo_despesa',
        'TIPO_DESPESA': 'tipo_despesa',
        'Tipo despesa': 'tipo_despesa',
        # supplier (fornecedor)
        'CD_CPF_CGC': 'fornecedor_documento',
        'CD_CPF_CNPJ_FORNECEDOR': 'fornecedor_documento',
        'NUMERO_CPF_CGC_FORNECEDOR': 'fornecedor_documento',
        'CPF/CNPJ do fornecedor': 'fornecedor_documento',
        'NO_FOR': 'fornecedor_nome',
        'NM_FORNECEDOR': 'fornecedor_nome',
        'NOME_FORNECEDOR': 'fornecedor_nome',
        'Nome do fornecedor': 'fornecedor_nome',
        'Nome do fornecedor (Receita Federal)': 'fornecedor_nome_receita',
        'Setor econômico do fornecedor': 'setor',
        # document / resource
        'NR_DOC_DESP': 'numero_do_documento',
        'DS_NR_DOCUMENTO': 'numero_do_documento',
        'NUMERO_DOCUMENTO': 'numero_do_documento',
        'Número do documento': 'numero_do_documento',
        'TP_RECURSO': 'especie_recurso',
        'DS_ESP_RECURSO': 'especie_recurso',
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
        # Municipal cycles (same pre-2018 schema). 2004 lacks CPF+SQ (name-based
        # recovery); 2008 lacks CPF but has SQ ((SQ, SG_UE) recovery); 2012/2016
        # carry "CPF do candidato" in-file.
        f'{path.data_dir}/TSE/2004/prestacao_contas_final/Candidato/Despesa/DespesaCandidato.csv',
        f'{path.data_dir}/TSE/2008/prestacao_contas_final/despesas_candidatos_2008_brasil.csv',
        f'{path.data_dir}/TSE/2012/prestacao_contas_final/despesas_candidatos_2012_brasil.txt',
        # 2016 candidate despesa files on disk are currently header-only (the
        # download's despesas were empty; receita 2016 is intact). The len(df)==0
        # guard in clean_file skips this until the real files are dropped in, so
        # it just works once TSE's despesas_candidatos_2016 are re-fetched.
        f'{path.data_dir}/TSE/2016/prestacao_contas_final/despesas_candidatos_prestacao_contas_final_2016_brasil.txt',
    ]
    for infile in infiles:
        clean_file(infile)

    with open('build/clean/despesa.txt', 'w') as f:
        f.write('Done')
