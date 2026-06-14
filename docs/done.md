# Done

Completed TODOs (moved out of `todo.md` so the active list stays scoped to current work).

- [x] **Improve poll candidate-name matcher (three concrete fixes)**
  - source: `source/clean/poll_2024.py` (`best_match` +
    new `_score_name`, `_strip_honorifics`, `_split_joint_ticket`
    helpers, `HONORIFICS`/`JOINT_SEP_RE` constants).
  - changes:
    1. `nome_urna_norm` is now a parallel target alongside
       `politico_norm` at scores 3/2/1 (not just score 4). Token
       overlap takes the max shared-token count across the two forms;
       substring at score 3 hits either form. Method label records
       which form won (`substring_urna`, `tokens_urna=…`).
    2. Leading honorifics are stripped from the poll-side normalized
       name before scoring; a second pass with the stripped form
       runs only when the original differs. `HONORIFICS` covers
       masculine + feminine variants (DR/DRA, PROF/PROFA, PE/PADRE,
       PR/PASTOR, BISPO/BISPA, MAJOR/CEL/CORONEL, CAP/CAPITAO,
       SGT/SARGENTO, CABO/SD/SOLDADO, TEN, COMANDANTE,
       DELEGADO/DELEGADA, VEREADOR/VEREADORA, PREFEITO/PREFEITA,
       MEDICO/MEDICA, ADVOGADO/ADVOGADA, …) plus a few less-common
       prefixes (FREI, IRMAO/IRMA, REVERENDO/REVERENDA, MISSIONARIO).
    3. Joint-ticket fallback: when the whole-name score is < 3, the
       poll string is split on ticket separators (`/`, `&`,
       en/em-dash, ` E `, ` COM `, ` - `) and each half is rescored
       (with and without honorifics). The split sub-match only wins
       if it scores strictly higher than the whole-name result, so
       a real name containing " E " or " - " isn't wrongly split.
  - matcher-side impact (174,747-row poll parquet, 2024 prefeito):
    - score ≥ 2 matched: 83,917 → 85,419 (+1,502, +1.8%)
    - score 4: 82,278 → 83,257 (+979)
    - score 3: 535 → 630 (+95)
    - score 2: 1,104 → 1,532 (+428)
    - score 1: 4,541 → 4,157 (−384; many promoted to 2+)
  - downstream impact in `projects/DOWNSTREAM_PROJECT`:
    `build/assemble/cand_poll.parquet` `matched_share == 1.0` rows
    21,030 → 22,665 (+1,635, +7.8%). Still below the original 85%
    aspirational target — see todo.md follow-up on stopword
    filtering + image-PDF re-extraction.
  - created: 2026-06-14
  - resolved: 2026-06-14

- [x] **Migrate `source/llm/poll_extract.py` to llmkit**
  - notes: split into `source/llm/schemas.py` (PollRelatorio inherits
    `ExtractionSchema`, schema_name="poll_relatorio" v1), prompt files
    under `source/llm/prompts/poll_relatorio_{system,user}.txt`, and a
    wrapper `source/llm/poll_relatorio.py` (`extract_poll_relatorio` —
    PDF-driven; cache lookup order: new llmkit composite key →
    legacy `{PROTOCOL}.json` in canonical and legacy-pilot-pilot dirs → fresh
    LLM call). The runner `source/llm/poll_extract.py` now calls the
    wrapper, adds `--states / --exclude-states` for UF filtering and a
    `--validate-cached` PDF-free mode that re-validates every cached
    entry against the current schema and assembles the parquet.
    Smoke test: `--validate-cached` against the 111-protocol legacy-pilot pilot
    produced 1,461 candidate-scenario rows from 102 polls (all
    validated against new schema, 0 schema failures). See
    `done.md` 2026-06-01 entry below for extraction-quality findings
    from the audit that the migration surfaced — they're prompt-level,
    not migration regressions.
    Live smoke test: 5 fresh RR-state PDFs (none in pilot) → 0
    validation failures after the system prompt was hardened to
    spell out the exact nested JSON schema (llmkit uses the legacy
    json_object response mode, which doesn't enforce schemas
    server-side; the in-prompt schema fills the gap). Cost
    $0.005 / 17s for 5 PDFs at 4 workers. Spot-checked
    RR-01685/2024 (Boa Vista, Globo/Quaest) against the PDF text:
    all vote percentages, party labels, and aggregate rows exact.
  - created: 2026-06-01
  - resolved: 2026-06-01

- [x] **2024 titulo-mismatch in SC and AL** (Bug 2 from the 2024 CPF
  recovery audit). Root cause was the same as Bug 1b: `get_candidates()`
  reads without `dtype=str`, so leading zeros in titulo were stripped.
  Fixed by `.str.zfill(12)` on both sides of the join. Post-fix: SC
  recovers 45.6%, AL 58.5% — in line with other states.
  - created: 2026-05-26
  - resolved: 2026-05-26

- [x] **2024 `status` column is 100% empty in `candidato.csv`**. TSE
  moved `DS_DETALHE_SITUACAO_CAND` to a separate
  `consulta_cand_complementar` file under the name
  `DS_SITUACAO_JULGAMENTO`. Fixed by reading the complementar file and
  joining on `SQ_CANDIDATO`. Post-fix: 100% coverage. Three new status
  values in 2024 vocabulary — see `docs/decisions.md` 2026-05-27 entry.
  - created: 2026-05-26
  - resolved: 2026-05-27

- [x] **Rebuild `candidato.csv` to populate `nome_urna`** *(load-bearing
  for the 2024 poll → candidate matcher)*. Candidato rebuilt with
  `nome_urna`, candidate matching folded into `poll_2024.py`
  (`poll_2024__candmatch.py` removed). National match rate: 61% of
  non-aggregate rows (82K via nome_urna alone).
  - created: 2026-05-28
  - resolved: 2026-06-02

- [x] **Stage a TSE partidos-CNPJ table for DOWNSTREAM_PROJECT Route C**
  Used `despesa_partidaria.csv` (2024 municipal-level rows, 42,829
  directorate CNPJs across 5,548 munis) as CNPJ→party×muni lookup.
  Route C added to `poll_sponsor_2024_join.py` (141 rows, 58 protocols).
  Also added Route D (party name parsing from sponsor name, 343 rows,
  149 protocols). Combined within-candidate overlap: 449 (up from 350
  with A+B only).
  - created: 2026-06-01
  - resolved: 2026-06-02

- [x] **Bulk poll-relatório LLM extraction (all UFs except SP)**
  Ran 2026-06-01 (10:20–15:12 UTC, `gpt-4o-mini`, 8 workers) over the
  legacy-pilot-fallback PDF dir at `projects/REDACTED-PROJECT/build/scrape/`
  `tse_relatorio/2024/`. New-format llmkit cache at
  `build/llm/poll_relatorio/`: **9,325 entries** (1 schema-invalid).
  Combined with 110 legacy-pilot legacy-pilot entries (48 AC + 62 AL + 1 stray
  at `projects/REDACTED-PROJECT/build/llm/poll_relatorio/`, picked up
  automatically by the wrapper's legacy fallback), all 25 non-SP UFs
  are covered. Parquet at `build/llm/poll_relatorio_2024.parquet`:
  149,934 candidate-scenario rows from 8,169 distinct polls. The
  ~1,500-protocol gap vs. the on-disk PDF count is dominated by
  image-only PDFs (TO 157, SE 39, ES 15, RS 15, ...) skipped at the
  `pdftotext`/`MIN_TEXT_CHARS=200` gate, plus a small per-UF
  schema-validation drop at parquet assembly. SP (1,635 PDFs) lives
  in the a separate host cache only and is 0 rows in the laptop parquet.
  Diagnosis note: an initial coverage check looking only at
  `_cache_meta.doc_id` distribution in the new cache wrongly suggested
  AC was completely missed (0 entries); the 48 AC files are in the legacy-pilot
  legacy pilot cache and are correctly merged in by
  `assemble_long_table()`. Verified by re-running `--states AC AL` →
  `cached: 190 / image_only: 6 / ok: 0`. See `data.md` "Coverage and
  known gaps" for the authoritative status, including the upstream
  scrape gap (3,415 protocols TSE never published + 89 transient
  errors retryable).
  - created: 2026-06-01
  - resolved: 2026-06-01 (coverage verified 2026-06-12)
