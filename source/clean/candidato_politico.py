import path
import pandas as pd
import numpy as np
import random
import os
import itertools
from glob import glob
from datetime import datetime
import diarios.clean as clean


def build_titulo_cpf_crosswalk():
    """Build titulo_eleitoral -> CPF mapping from years that have both."""
    print('Building titulo->CPF crosswalk from 1998-2022...')
    rows = []
    for year in [str(y) for y in range(1998, 2023, 2)]:
        pattern = os.path.join(path.data_dir, 'TSE', year, 'consulta_cand',
                               f'consulta_cand_{year}_*.csv')
        for f in glob(pattern):
            df = pd.read_csv(f, encoding='latin1', sep=';',
                             usecols=['NR_CPF_CANDIDATO', 'NR_TITULO_ELEITORAL_CANDIDATO'],
                             dtype=str)
            rows.append(df)
    xwalk = pd.concat(rows, ignore_index=True)
    xwalk = xwalk.rename(columns={
        'NR_TITULO_ELEITORAL_CANDIDATO': 'titulo',
        'NR_CPF_CANDIDATO': 'cpf_from_titulo',
    })
    xwalk['cpf_from_titulo'] = clean.clean_cpf(xwalk['cpf_from_titulo'])
    xwalk['titulo'] = xwalk['titulo'].str.zfill(12)
    xwalk = xwalk.dropna(subset=['cpf_from_titulo', 'titulo'])
    xwalk = xwalk.drop_duplicates('titulo')
    print(f'  Crosswalk: {len(xwalk)} unique titulo->CPF mappings')
    return xwalk


TITULO_CPF_XWALK = None


def main():
    random.seed(42)
    candidato_file = 'build/clean/candidato.csv'
    politico_file = 'build/clean/politico.csv'
    years = [
        '1998',
        '2000',
        '2002',
        '2004',
        '2006',
        '2008',
        '2010',
        '2012',
        '2014',
        '2016',
        '2018',
        '2020',
        '2022',
        '2024',
    ]  # 1994 and 1996 does not have CPF and is missing for many states
    states = [
        'AC',
        'SP',
        'RJ',
        'MG',
        'BA',
        'RS',
        'AL',
        'AM',
        'AP',
        'CE',
        'DF',
        'ES',
        'GO',
        'MA',
        'MS',
        'MT',
        'PA',
        'PB',
        'PE',
        'PI',
        'PR',
        'RN',
        'RO',
        'RR',
        'RS',
        'SC',
        'SE',
        'TO',
    ]
    #years = ['2000']
    #states = ['AC', 'AL']
    years, states = multiply_cartesian(years, states)
    results = pd.concat(map(clean_election, states, years), sort=True)
    # Build politico_id: use CPF when available, fall back to titulo
    cpf_str = results['cpf'].astype(str).where(results['cpf'].notna())
    titulo_str = (results.get('titulo', pd.Series(dtype=str))
                  .astype(str).str.strip().str.replace(r'\D', '', regex=True))
    titulo_str = titulo_str.where(titulo_str != '')
    politico_id = cpf_str.fillna('T' + titulo_str)
    results['politico_id'] = politico_id
    results = results.query('politico_id.notnull()')
    cols = {
        'politico_id',
        'cpf',
        'titulo',
        'politico',
        'race',
        'nationality',
        'birthdate',
        'gender',
        'birth_municipio_id',
        'birth_municipio',
        'birth_estado_id',
        'birth_estado',
    }.intersection(results.columns)
    politico = results.drop_duplicates(subset='politico_id').loc[:, list(cols)]
    cols = {
        'eleicao',
        'politico_id',
        'cpf',
        'titulo',
        'year',
        'suplementar',
        'estado',
        'estado_id',
        'municipio',
        'municipio_id',
        'office',
        'round',
        'status',
        'party',
        'votes',
        'elected',
        'electeddummy',
        'margin',
        'rank',
        'close',
        'coalition',
        'campaignexpenditure',
        'education',
        'marital_status',
        'occupation',
        'NUMERO_CAND',
        'SQ_CANDIDATO',
    }.intersection(results.columns)
    candidato = results.loc[:, list(cols)]
    candidato['ibge7'] = clean.transform(candidato['municipio_id'], 'municipio_id', 'ibge7')
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
        path.data_dir, 'TSE', year, 'votacao_candidato_munzona',
        'votacao_candidato_munzona_{0}_{1}.txt'.format(year, state))
    columns_file = os.path.join(path.data_dir, 'TSE', year,
                                'votacao_candidato_munzona',
                                'variable-description.csv')
    if year in ['2016', '2018', '2020', '2022', '2024']:
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
    if year in ['2016', '2018', '2020', '2022', '2024']:
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
            'NR_CANDIDATO': 'NUMERO_CAND',
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
            'NUMERO_CAND': 'NUMERO_CAND',
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
        'eleicao',
        'district',
        'office',
        'round',
        'elected',
        'NUMERO_CAND',
        'SQ_CANDIDATO',
        'politico',
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
        '2º TURNO': 'second round',
    }


def add_office_type(results):
    results.loc[results.office.str.
                match('VEREADOR|DEPUTADO ESTADUAL|DEPUTADO FEDERAL'),
                'office_type'] = 'pr'
    results.loc[
        results.office.str.match('PREFEITO|GOVERNADOR|PRESIDENTE|SENADOR'),
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
    results.drop(
        columns=[
            'electedvotes',
            'notelectedvotes',
            'upperthreshold_pr',
            'upperthreshold_majority',
            'lowerthreshold_pr',
            'lowerthreshold_majority',
            'nseats',
            'totalvotes',
        ],
        inplace=True,
    )
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
    global TITULO_CPF_XWALK
    infile = os.path.join(path.data_dir, 'TSE', year, 'consulta_cand',
                          'consulta_cand_{0}_{1}.csv'.format(year, state))

    df = pd.read_csv(infile, encoding='latin1', sep=';')
    # TSE redacted CPFs from 2024 onwards; recover via titulo_eleitoral crosswalk.
    # Row-level coalesce: attempt recovery whenever any sentinel/blank CPF is
    # present in this state file, and only overwrite the sentinel rows. The
    # prior state-level `.all()` guard skipped recovery entirely whenever even
    # one row had a non-sentinel value (blank, "0", whitespace), which silently
    # zeroed out recovery for ~23 of 27 states in 2024.
    if ('NR_TITULO_ELEITORAL_CANDIDATO' in df.columns
            and 'NR_CPF_CANDIDATO' in df.columns):
        cpf_str = df['NR_CPF_CANDIDATO'].astype(str).str.strip('" ')
        sentinel = cpf_str.isin(['-1', '-4', '-5', '', 'nan', '0'])
        if sentinel.any():
            if TITULO_CPF_XWALK is None:
                TITULO_CPF_XWALK = build_titulo_cpf_crosswalk()
            df['titulo_key'] = df['NR_TITULO_ELEITORAL_CANDIDATO'].astype(str).str.zfill(12)
            df = df.merge(TITULO_CPF_XWALK, left_on='titulo_key',
                          right_on='titulo', how='left')
            recovered = sentinel & df['cpf_from_titulo'].notna()
            df.loc[recovered, 'NR_CPF_CANDIDATO'] = df.loc[recovered, 'cpf_from_titulo']
            print(f'  CPF recovery via titulo: {recovered.sum()}/{sentinel.sum()} '
                  f'sentinels recovered ({len(df)} total rows)')
            df = df.drop(columns=['titulo_key', 'titulo', 'cpf_from_titulo'])
    # TSE moved DS_DETALHE_SITUACAO_CAND to the complementar file in 2024,
    # under the name DS_SITUACAO_JULGAMENTO. If the main file lacks the
    # column or has only #NE/#NULO values, recover from complementar.
    status_col = 'DS_DETALHE_SITUACAO_CAND'
    status_missing = (status_col not in df.columns
                      or df[status_col].astype(str).str.strip('" ')
                      .isin(['#NE', '#NE#', '#NULO#', '', 'nan']).all())
    if status_missing:
        compl_file = os.path.join(
            path.data_dir, 'TSE', year, 'consulta_cand_complementar',
            'consulta_cand_complementar_{0}_{1}.csv'.format(year, state))
        if os.path.exists(compl_file):
            compl = pd.read_csv(compl_file, encoding='latin1', sep=';',
                                usecols=['SQ_CANDIDATO', 'DS_SITUACAO_JULGAMENTO'],
                                dtype=str)
            compl = compl.rename(columns={'DS_SITUACAO_JULGAMENTO': status_col})
            compl = compl.dropna(subset=[status_col])
            compl = compl[compl[status_col].str.strip('" ') != '#NE']
            if len(compl) > 0:
                compl['SQ_CANDIDATO'] = pd.to_numeric(
                    compl['SQ_CANDIDATO'], errors='coerce').astype(
                    df['SQ_CANDIDATO'].dtype)
                compl = compl.drop_duplicates('SQ_CANDIDATO')
                if status_col in df.columns:
                    df = df.drop(columns=[status_col])
                df = df.merge(compl, on='SQ_CANDIDATO', how='left')
                filled = df[status_col].notna().sum()
                print(f'  Status recovery from complementar: {filled}/{len(df)} rows')
    cols = get_candidate_column_mapping()
    df = df.rename(columns=cols)
    new_cols = set(df.columns).intersection(cols.values())
    df = df.loc[:, list(new_cols)]
    return df


def get_candidate_column_mapping():
    return {
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
        'NR_DESPESA_MAX_CAMPANHA': 'campaignexpenditure',
        'VR_DESPESA_MAX_CAMPANHA': 'campaignexpenditure',
        'NR_TITULO_ELEITORAL_CANDIDATO': 'titulo',
    }



def clean_candidates(candidates, year):
    candidates = clean.clean_text_columns(
        candidates,
        exclude=[
            'estado',
            'birth_estado',
            'birthdate',
            'party',
            'coalition',
            'titulo',
        ],
    )
    candidates['birth_estado_id'] = clean.transform(candidates['birth_estado'],
                                                    'estado', 'estado_id')
    candidates['estado_id'] = clean.transform(candidates['estado'], 'estado',
                                              'estado_id')
    candidates['coalition'] = candidates['coalition'].fillna('#NULO#')
    candidates['coalition'] = candidates.apply(clean_coalition, axis=1)
    candidates['cpf'] = clean.clean_cpf(candidates.cpf)
    candidates['politico'] = clean.clean_text(candidates['politico'])
    if int(year) % 4 == 0:
        candidates['municipio_id'] = candidates['district']
    dedup_cols = ['district', 'office', 'NUMERO_CAND', 'SQ_CANDIDATO']
    if candidates['cpf'].notna().any():
        dedup_cols.append('cpf')
    candidates = candidates.drop_duplicates(subset=dedup_cols)
    candidates['birthdate'] = clean_birth_date(candidates.birthdate, year)
    return candidates


def clean_coalition(row):
    if row['coalition'] in ['#NULO#', '#NE#']:
        return row['party'].strip()
    else:
        return row['coalition'].strip()


def clean_birth_date(dates, year):
    date_format = '%d/%m/%Y'
    dates = pd.to_datetime(dates, format=date_format, errors='coerce')
    dates = dates.apply(string_from_date)
    print(dates.sample(10))
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
        # NUMERO_CAND differ some times across cand and results files
        # Should be sufficient to merge by SQ_CANDIDATO
        merge_vars = ['district', 'office', 'SQ_CANDIDATO', 'politico']
        results.drop(columns=['NUMERO_CAND'], inplace=True)
    return pd.merge(
        results,
        candidates,
        on=merge_vars,
        how='outer',
    )  # .drop(columns=['NUMERO_CAND', 'SQ_CANDIDATO'])


politico, candidato = main()
