# Summary

## What this pipeline does

- Cleans and loads Brazilian political data into a SQLite database (politica.db)
- Data covers candidatos (candidates), bens (assets), receitas (campaign revenue), and eleicoes (elections)
- Source data from TSE (Tribunal Superior Eleitoral)

## Pipeline stages

1. **Raw** (`source/raw/`): raw reference data (eleicoes.csv)
2. **Clean** (`source/clean/`): cleans TSE election data into structured CSVs
   - candidato_politico.py: produces candidato.csv and politico.csv
   - bem.py: cleans asset declarations (bem)
   - receita.py: cleans campaign revenue data (receita)
   - eleicao.py: cleans election results (eleicao.csv)
3. **Insert** (`source/insert/`): loads all cleaned CSVs into SQLite database (`build/insert/politica.db`)

## Build system

- Uses SCons (`SConstruct`) to define the build graph
