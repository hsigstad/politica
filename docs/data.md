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

## Output: 2024 poll relatório LLM extractions

Per-candidate vote intentions extracted from the 2024 TSE-registered poll
relatório PDFs (`pesquisa_eleitoral`). Produced by `source/llm/poll_extract.py`
(runner) via `source/llm/poll_relatorio.py` (llmkit wrapper); schema in
`source/llm/schemas.py` (`PollRelatorio`, `schema_version = "v1"`).

### Location
- `build/llm/poll_relatorio_2024.parquet` — assembled long table.
- `build/llm/poll_relatorio/<hash>.json` — raw llmkit cache, one file per
  poll (composite-key filenames). Not committed (292 MB); see external-mirror below.

### Unit of observation
One row per **candidate × scenario × poll**. 149,934 rows from 8,169 distinct
polls across 25 states.

### Columns
- `protocol` — TSE protocol, compact form (e.g. `PE004282024`); join key to
  the registration CSVs and relatório PDFs.
- `tse_protocol_display` — human-readable protocol (e.g. `PE-00428/2024`),
  echoed from the PDF for join-back validation.
- `scenario_type` — controlled vocabulary: `espontaneo`, `estimulado`,
  `votos_validos`, `rejeicao`, `avaliacao_governo`,
  `segundo_turno_simulacao`, `outro` (a few stray buckets like
  `expectativa_vitoria` leak from `outro`; treat anything outside the seven
  as `outro`).
- `scenario_label` — exact label as printed in the PDF.
- `candidate_name` — candidate display name; aggregate rows carry descriptive
  labels (`Branco/Nulo`, `Não sabe`, ...).
- `party` — party abbreviation when shown next to the name, else null.
- `percent` — vote-intention percentage in that scenario, 0–100.
- `extraction_notes` — per-poll note on any ambiguity or judgment call.
- `source` — extraction provenance tag (`llmkit`).

### external-mirror
Both outputs are mirrored alongside the source relatórios at
`EXTERNAL_MIRROR`:
- `poll_relatorio_2024.parquet` (the table above).
- `poll_relatorio_cache.tar.zst` (the raw JSON cache, 292 MB → 21 MB;
  restore with `tar --use-compress-program='zstd -d' -xf` → `poll_relatorio/`).
