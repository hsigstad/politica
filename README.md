# politica

A pipeline that cleans and assembles Brazilian political data from the
Tribunal Superior Eleitoral (TSE) into structured tables — candidates,
assets, campaign finance, election results, party organs, electoral-court
cases, and registered opinion polls — usable as a relational database or
as analysis-ready CSV/parquet files.

There are two sub-pipelines:

1. **Core political data** — candidates, assets, revenue/expenses,
   election results, party data, and processual (court-case) metadata,
   1998–2024.
2. **2024 poll pipeline** — scrapes registered opinion-poll report PDFs,
   extracts vote intentions with an LLM, cleans them, matches candidates
   to the TSE registry, and links poll sponsors.

## Data sources

All raw inputs are **public**:

- **TSE open data** (`dadosabertos.tse.jus.br`), the *Repositório de
  Dados Eleitorais* — bulk per-year, per-dataset CSV/TXT bundles. This is
  the source for candidates, assets, campaign finance, results, party
  data, processual data, and poll registrations.
- **TSE divulgação de pesquisas** (`pesqele-divulgacao.tse.jus.br`) — the
  per-protocol opinion-poll report PDFs (*relatórios*) scraped by the
  poll pipeline.
- **pollingdata.com.br** — an aggregated long-format export of 2012–2020
  mayoral polls (`polls_prefeito.csv`), used only for the 2020 poll table.

The pipeline never bundles raw data. You stage the TSE bundles yourself
(see below) and point `DATA_DIR` at them.

## Required raw inputs

Scripts read from `$DATA_DIR`, expecting the TSE bundles unpacked under a
`TSE/{year}/<dataset>/` layout. The main datasets consumed:

```
$DATA_DIR/TSE/{year}/
  consulta_cand/                 candidate registrations  (+ consulta_cand_complementar for 2024)
  bem_candidato/                 asset declarations
  prestacao_contas_final/        campaign revenue + expenses (2024: prestacao_de_contas_eleitorais_candidatos)
  votacao_secao/                 section-level results
  detalhe_votacao_munzona/       muni-zone result details
  processos_eleitorais/          processual metadata, assuntos, decisões, recursos
  orgao_partidario/ delegado_partidario/ perfil_filiacao_partidaria/   party data
  motivo_cassacao/               candidacy-rejection reasons
  perfil_eleitorado/             electorate profile
  pesquisa_eleitoral/ pesquisa_contratante/ pesquisa_pagante/          poll registrations + sponsors
```

Not every stage needs every dataset — see `docs/data.md` for what each
consumes and `docs/summary.md` for the stage-by-stage flow. Exact bundle
names vary by year (TSE renamed several files in 2024); the clean scripts
document the per-year specifics inline.

## Dependencies

- Python 3.11+, `pandas`, `python-dotenv`, `sqlalchemy`, `scons`
- [`diarios`](https://github.com/hsigstad/diarios) — shared cleaning
  utilities (`diarios.clean`, `diarios.database`)
- [`llmkit`](https://github.com/hsigstad/llmkit) — LLM extraction
  framework (cache + Pydantic validation), used by the poll pipeline
- An OpenAI API key (`OPENAI_API_KEY`) for the poll-extraction stage

## Setup

```bash
cp .env.example .env      # then fill in the values
```

`.env` defines:

- `BASE_DIR` — absolute path to this repo root
- `DATA_DIR` — absolute path to the staged TSE data root
- `POSTGRESQL_*` — optional, only for loading into PostgreSQL
  (`insert_postgresql.py`); the default SQLite path needs none

## Running

**Core pipeline** — a SCons build graph:

```bash
scons                      # clean → build/clean/*, then load build/insert/politica.db
```

**Poll pipeline** — not yet in SCons; run the stages in order:

```bash
python source/scrape/tse_relatorio.py --year 2024        # download poll PDFs
python source/llm/poll_extract.py    --year 2024         # LLM-extract vote intentions
python source/clean/poll_response_2024.py                # clean + match to registry
python source/clean/poll_sponsor.py                      # clean + link sponsors
```

See `docs/reference/poll_relatorio_2024.md` for the poll dataset's
columns, coverage, and known gaps.

## Repository layout

```
source/
  raw/       reference lookups (e.g. eleicoes.csv)
  clean/     TSE bulk data → structured CSV/parquet
  llm/       LLM extraction of poll reports (schemas + prompts)
  scrape/    poll-report PDF downloader
  insert/    load cleaned tables into SQLite / PostgreSQL
build/        all script outputs (gitignored; regenerable)
docs/         pipeline documentation (see docs/summary.md)
```

## Documentation

`docs/summary.md` is the entry point. `docs/data.md` describes inputs and
outputs; `docs/decisions.md` records design decisions.

## License

MIT — see `LICENSE`.
