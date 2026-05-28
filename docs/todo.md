# TODOs

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

- [ ] **Retire LEGACY_TRE_DIARIOS `tse_processos.py` once paper is post-acceptance**
  - notes: politica's `processo.py` now covers the same TSE bulk processo
    data the LEGACY_TRE_DIARIOS script cleans, but the two outputs are not
    drop-in-equivalent (classe transform, assunto1..4 split, dedup). See
    `docs/decisions.md` 2026-05-26 entry for the schema diff and the
    migration recipe. Live consumer:
    `projects/REDACTED-PROJECT/source/query/proc__tse.py`.
  - created: 2026-05-26
