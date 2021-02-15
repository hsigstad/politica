import path
import pandas as pd
import re
from glob import glob


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
                     })
    cols = get_cols()
    df = df.rename(columns=cols).loc[:, cols.values()]
    outfile = infile.replace('.txt', '.csv')
    outfile = outfile.replace('prestacao_contas_final/',
                              'prestacao_contas_final/clean/')
    df.to_csv(outfile, index=False)
    return df


def get_cols():
    cols = {
        'Sequencial Candidato': 'SQ_CANDIDATO',
        'UF': 'estado',
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
        'Descricao da receita': 'descricao_receita'
    }
    return cols


infiles = glob(
    os.path.join(path.local_data_dir,
                 'TSE/*/prestacao_contas_final/receitas_candidatos*txt'))

df = pd.concat(map(clean_file, infiles))
