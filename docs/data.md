# Data

## Input: TSE election data

### Source
- provider: Tribunal Superior Eleitoral (TSE)
- access: publicly available election data files

### Coverage
- Brazilian elections (federal, state, municipal)

## Output: Cleaned CSVs

### Location
- `build/clean/candidato.csv` — candidate-level data
- `build/clean/politico.csv` — politician-level data (deduplicated across elections)
- `build/clean/bem.txt` — asset declaration data (completion flag)
- `build/clean/receita.txt` — campaign revenue data (completion flag)
- `build/clean/eleicao.csv` — election results

## Output: SQLite database

### Location
- `build/insert/politica.db`

### Tables
- candidato: candidate-election level data
- politico: politician-level data
- bem: asset declarations
- receita: campaign revenue
- eleicao: election results
