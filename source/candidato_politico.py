import path
import pandas as pd
import numpy as np
import random
import os
import itertools
from datetime import datetime
import sys
sys.path.append('/home/henrik/external-mirror/brazil/diarios')
os.chdir('/home/henrik/external-mirror/brazil/politica')
import diarios.clean as clean


def main():
    random.seed(42)
    candidato_file = 'build/clean/candidato.csv'
    politico_file = 'build/clean/politico.csv'
    years = [
        '1998', '2000', '2002', '2004', '2006', '2008', '2010', '2012', '2014',
        '2016', '2018'
    ]  # 1994 and 1996 does not have CPF, and is missing for many states
    states = [
        'AC', 'SP', 'RJ', 'MG', 'BA', 'RS', 'AL', 'AM', 'AP', 'CE', 'DF', 'ES',
        'GO', 'MA', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'PR', 'RN', 'RO', 'RR',
        'RS', 'SC', 'SE', 'TO'
    ]
    # years = ['2004']
    # states = ['AC']
    years, states = multiply_cartesian(years, states)
    results = pd.concat(map(clean_election, states, years), sort=True)
    results = results.query('cpf.notnull()')  #NB!
    cols = {
        'cpf', 'politico', 'race', 'nationality', 'birthdate', 'gender',
        'birth_municipio_id', 'birth_municipio', 'birth_estado_id',
        'birth_estado'
    }.intersection(results.columns)
    politico = results.drop_duplicates(subset='cpf').loc[:, cols]
    cols = {
        'eleicao', 'cpf', 'year', 'suplementar', 'estado', 'estado_id',
        'municipio', 'municipio_id', 'office', 'round', 'status', 'party',
        'votes', 'elected', 'electeddummy', 'margin', 'rank', 'close',
        'coalition', 'campaignexpenditure', 'education', 'marital_status',
        'occupation', 'NUMERO_CAND', 'SQ_CANDIDATO'
    }.intersection(results.columns)
    candidato = results.loc[:, cols]
    candidato.to_csv(candidato_file, index=False)
    politico.to_csv(politico_file, index=False)
    return politico, candidato


def multiply_cartesian(list1, list2):
    outlist1 = []
    outlist2 = []
    for v1, v2 in itertools.product(list1, list2):
        outlist1 += [v1]
        outlist2 += [v2]
    return outlist1, outlist2


def clean_election(state, year):
    print('{0} {1}'.format(state, year))
    try:
        results = get_election_results(state, year)
        candidates = get_candidates(state, year)
    except FileNotFoundError:
        print('File not found')
        return pd.DataFrame()
    results = rename_columns(results, year)
    municipio_names = get_municipio_names(results)
    results = collapse_by_candidate(results, year)
    results = clean_variables(results, year)
    candidates = clean_candidates(candidates, year)
    results = merge_in_candidates(results, candidates, year=year)
    if int(year) % 4 == 0:
        results = pd.merge(results,
                           municipio_names,
                           on='municipio_id',
                           how='left')
    results = add_office_type(results)
    results = add_win_margin(results)
    return results


def get_election_results(state, year):
    infile = os.path.join(
        path.external-mirror_dir, 'elections', year, 'votacao_candidato_munzona',
        'votacao_candidato_munzona_{0}_{1}.txt'.format(year, state))
    columns_file = os.path.join(path.external-mirror_dir, 'elections', year,
                                'votacao_candidato_munzona',
                                'variable-description.csv')
    if year == '2018':
        infile = infile.replace('.txt', '.csv')
        results = pd.read_csv(infile, encoding='latin1', sep=';')
    else:
        results = pd.read_csv(infile, encoding='latin1', sep=';', header=None)
        columns = pd.read_csv(columns_file, sep=';')
        results.columns = columns['variable']
    return results


def rename_columns(results, year):
    column_mapping = get_column_mapping(year)
    return (results.loc[:,
                        column_mapping.keys()].rename(columns=column_mapping))


def get_column_mapping(year):
    if year == '2018':
        mapping = {
            'NM_CANDIDATO': 'politico',
            'DS_ELEICAO': 'eleicao',
            'SG_UF': 'estado',
            'DS_CARGO': 'office',
            'DS_SIT_TOT_TURNO': 'elected',
            'NR_TURNO': 'round',
            'CD_MUNICIPIO': 'municipio_id',
            'NM_MUNICIPIO': 'municipio',
            'QT_VOTOS_NOMINAIS': 'votes',
            'SG_UE': 'SIGLA_UE',
            'SQ_CANDIDATO': 'SQ_CANDIDATO',
            'NR_CANDIDATO': 'NUMERO_CAND'
        }
    else:
        mapping = {
            'NOME_CANDIDATO': 'politico',
            'DESCRICAO_ELEICAO': 'eleicao',
            'SIGLA_UF': 'estado',
            'DESCRICAO_CARGO': 'office',
            'DESC_SIT_CAND_TOT': 'elected',
            'NUM_TURNO': 'round',
            'CODIGO_MUNICIPIO': 'municipio_id',
            'NOME_MUNICIPIO': 'municipio',
            'TOTAL_VOTOS': 'votes',
            'SIGLA_UE': 'SIGLA_UE',
            'SQ_CANDIDATO': 'SQ_CANDIDATO',
            'NUMERO_CAND': 'NUMERO_CAND'
        }
    return mapping


def get_municipio_names(results):
    names = clean.clean_text_columns(
        results.loc[:, ('municipio', 'municipio_id')].drop_duplicates())
    return names


def collapse_by_candidate(results, year):
    if int(year) % 4 == 0:
        results['district'] = results['SIGLA_UE']
    else:
        results['district'] = results['estado']
    columns = [
        'eleicao', 'district', 'office', 'round', 'elected', 'NUMERO_CAND',
        'SQ_CANDIDATO', 'politico'
    ]
    return results.groupby(columns, as_index=False).agg({'votes': np.sum})


def clean_variables(results, year):
    results['elected'] = results['elected'].map(get_elected_mapping())
    results['electeddummy'] = results['elected'].str.match('elected').astype(
        float)
    results = clean.clean_text_columns(results)
    results['politico'] = clean.clean_text(results['politico'])
    results['suplementar'] = (
        results.eleicao.fillna('').str.contains('suplem|nova')) * 1
    if int(year) % 4 == 0:
        results['district'] = pd.to_numeric(
            results['district'].apply(clean_district), errors='coerce')
    return results


def clean_district(district):
    if district == 'sp':
        district = '71072'
    return district


def get_elected_mapping():
    return {
        'ELEITO': 'elected',
        'MÉDIA': 'elected',
        'ELEITO POR MÉDIA': 'elected',
        'ELEITO POR QP': 'elected',
        'SUPLENTE': 'deputy',
        'NÃO ELEITO': 'not elected',
        '2º TURNO': 'second round'
    }


def add_office_type(results):
    results.loc[results.office.str.
                match('vereador|deputado estadual|deputado federal'),
                'office_type'] = 'pr'
    results.loc[
        results.office.str.match('prefeito|governador|presidente|senador'),
        'office_type'] = 'majority'
    return results


def add_win_margin(results):
    # upperthreshold: the votes of the person who got
    # elected who got the fewest votes
    # lowerthreshold: the votes of the person who did
    # not get elected who got the most votes
    results.loc[results['electeddummy'] == True,
                'electedvotes'] = results['votes']
    results.loc[results['electeddummy'] == False,
                'notelectedvotes'] = results['votes']
    results['upperthreshold_pr'] = (results.groupby(
        ['year', 'district', 'office', 'round', 'coalition',
         'suplementar'])['electedvotes'].transform('min'))
    results['upperthreshold_majority'] = (results.groupby(
        ['year', 'district', 'office', 'round',
         'suplementar'])['electedvotes'].transform('min'))
    results['lowerthreshold_pr'] = (results.groupby(
        ['year', 'district', 'office', 'round', 'coalition',
         'suplementar'])['notelectedvotes'].transform('max'))
    results['lowerthreshold_majority'] = (results.groupby(
        ['year', 'district', 'office', 'round',
         'suplementar'])['notelectedvotes'].transform('max'))
    grouped = results.groupby(['district', 'office', 'round', 'suplementar'])
    results['nseats'] = grouped['electeddummy'].transform('sum')
    results['totalvotes'] = grouped['votes'].transform('sum')
    results['margin'] = results.apply(calculate_win_margin, axis=1)
    results.drop(columns=[
        'electedvotes', 'notelectedvotes', 'upperthreshold_pr',
        'upperthreshold_majority', 'lowerthreshold_pr',
        'lowerthreshold_majority', 'nseats', 'totalvotes'
    ],
                 inplace=True)
    return results


def calculate_win_margin(row):
    if row.totalvotes == 0:
        return np.nan
    if not row['office_type'] in ['pr', 'majority']:
        return np.nan
    if row['office_type'] == 'majority' and row['electeddummy']:
        threshold = row['lowerthreshold_majority']
    if row['office_type'] == 'majority' and not row['electeddummy']:
        threshold = row['upperthreshold_majority']
    if row['office_type'] == 'pr' and row['electeddummy']:
        threshold = row['lowerthreshold_pr']
    if row['office_type'] == 'pr' and not row['electeddummy']:
        threshold = row['upperthreshold_pr']
    return (row['votes'] - threshold) * row['nseats'] / row['totalvotes']


def get_candidates(state, year):
    infile = os.path.join(path.external-mirror_dir, 'elections', year, 'consulta_cand',
                          'consulta_cand_{0}_{1}.txt'.format(year, state))
    column_mapping = get_candidate_column_mapping(year)
    if year == '2018':
        candidates = pd.read_csv(infile.replace('.txt', '.csv'),
                                 encoding='latin1',
                                 sep=';')
    else:
        candidates = pd.read_csv(infile,
                                 encoding='latin1',
                                 sep=';',
                                 header=None)
    return (candidates.loc[:, column_mapping.keys()].rename(
        columns=column_mapping))


def get_candidate_column_mapping(year):
    if year in ['2014', '2016']:
        mapping = {
            2: 'year',
            5: 'estado',
            6: 'district',
            9: 'office',
            10: 'politico',
            11: 'SQ_CANDIDATO',
            12: 'NUMERO_CAND',
            13: 'cpf',
            16: 'status',
            18: 'party',
            22: 'coalition',
            23: 'coalitionname',
            25: 'occupation',
            26: 'birthdate',
            30: 'gender',
            32: 'education',
            34: 'marital_status',
            36: 'race',
            38: 'nationality',
            39: 'birth_estado',
            40: 'birth_municipio_id',
            41: 'birth_municipio',
            42: 'campaignexpenditure'
        }
    elif year == '2018':
        mapping = {
            'ANO_ELEICAO': 'year',
            'SG_UF': 'estado',
            'SG_UE': 'district',
            'DS_CARGO': 'office',
            'SQ_CANDIDATO': 'SQ_CANDIDATO',
            'NR_CANDIDATO': 'NUMERO_CAND',
            'NM_CANDIDATO': 'politico',
            'NR_CPF_CANDIDATO': 'cpf',
            'DS_DETALHE_SITUACAO_CAND': 'status',
            'SG_PARTIDO': 'party',
            'NM_COLIGACAO': 'coalitionname',
            'DS_COMPOSICAO_COLIGACAO': 'coalition',
            'DS_NACIONALIDADE': 'nationality',
            'SG_UF_NASCIMENTO': 'birth_estado',
            'CD_MUNICIPIO_NASCIMENTO': 'birth_municipio_id',
            'NM_MUNICIPIO_NASCIMENTO': 'birth_municipio',
            'DT_NASCIMENTO': 'birthdate',
            'DS_GENERO': 'gender',
            'DS_GRAU_INSTRUCAO': 'education',
            'DS_ESTADO_CIVIL': 'marital_status',
            'DS_COR_RACA': 'race',
            'DS_OCUPACAO': 'occupation',
            'NR_DESPESA_MAX_CAMPANHA': 'campaignexpenditure'
        }
    else:
        mapping = {
            2: 'year',
            5: 'estado',
            6: 'district',
            9: 'office',
            10: 'politico',
            11: 'SQ_CANDIDATO',
            12: 'NUMERO_CAND',
            13: 'cpf',
            16: 'status',
            18: 'party',
            22: 'coalition',
            23: 'coalitionname',
            25: 'occupation',
            26: 'birthdate',
            30: 'gender',
            32: 'education',
            34: 'marital_status',
            36: 'nationality',
            37: 'birth_estado',
            38: 'birth_municipio_id',
            39: 'birth_municipio',
            40: 'campaignexpenditure'
        }
    return mapping


def clean_candidates(candidates, year):
    candidates = clean.clean_text_columns(
        candidates, exclude=['estado', 'birth_estado', 'party', 'coalition'])
    candidates['birth_estado_id'] = clean.transform(candidates['birth_estado'],
                                                    'estado', 'estado_id')
    candidates['estado_id'] = clean.transform(candidates['estado'], 'estado',
                                              'estado_id')
    candidates['coalition'] = candidates['coalition'].fillna('#NULO#')
    candidates['coalition'] = candidates.apply(clean_coalition, axis=1)
    candidates['cpf'] = pd.to_numeric(candidates['cpf'], errors='coerce')
    candidates['politico'] = clean.clean_text(candidates['politico'])
    if int(year) % 4 == 0:
        candidates['municipio_id'] = candidates['district']
    candidates = candidates.drop_duplicates(
        subset=['district', 'office', 'NUMERO_CAND', 'SQ_CANDIDATO', 'cpf'])
    candidates['birthdate'] = clean_birth_date(candidates.birthdate, year)
    return candidates


def clean_coalition(row):
    if row['coalition'] in ['#NULO#', '#NE#']:
        return row['party'].strip()
    else:
        return row['coalition'].strip()


def clean_birth_date(dates, year):
    if year in ['1994', '1996', '2010']:
        dates.replace({'([0-9]{2})$': r'19\1'}, regex=True, inplace=True)
    if year in ['1998', '2000', '2002', '2004']:
        if dates.dtype != 'object':
            dates = dates.apply('{:08.0f}'.format)
        date_format = '%d%m%Y'
    elif year in ['1994', '2010']:
        date_format = '%d-%b-%Y'
    else:
        date_format = '%d/%m/%Y'
    dates = pd.to_datetime(dates, format=date_format, errors='coerce')
    dates = dates.apply(string_from_date)
    return dates


def string_from_date(date):
    try:
        return datetime.strftime(date, '%Y-%m-%d')
    except:
        return ''


def merge_in_candidates(results, candidates, year):
    if year == '2000':
        merge_vars = ['district', 'office', 'NUMERO_CAND', 'politico']
        results.drop(columns=['SQ_CANDIDATO'], inplace=True)
    else:
        merge_vars = ['district', 'office', 'NUMERO_CAND', 'SQ_CANDIDATO']
        results.drop(columns=['politico'], inplace=True)
    return pd.merge(
        results, candidates, on=merge_vars,
        how='outer')  # .drop(columns=['NUMERO_CAND', 'SQ_CANDIDATO'])


politico, candidato = main()
