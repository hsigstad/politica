# Done

Completed TODOs (moved out of `todo.md` so the active list stays scoped to current work).

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
