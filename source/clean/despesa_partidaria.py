import path
import pandas as pd
from glob import glob

infiles = glob(
    os.path.join(
        path.data_dir, 'TSE', '*', 
        'prestacao_contas_anual_partidaria',
        'despesa_anual_2*.csv'
    )
)


def read_csv(infile):
    return pd.read_csv(infile, sep=';', encoding='latin1')

def clean_value(value):
    return pd.to_numeric(value.str.replace(',', '.', regex=False))

df = pd.concat(map(read_csv, infiles))
for c in ['VR_GASTO', 'VR_PAGAMENTO', 'VR_DOCUMENTO']:
    df[c] = clean_value(df[c])


df.to_csv('build/clean/despesa_partidaria.csv', index=False)
