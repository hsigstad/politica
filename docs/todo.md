# TODOs

- [ ] **Retire LEGACY_TRE_DIARIOS `tse_processos.py` once paper is post-acceptance**
  - notes: politica's `processo.py` now covers the same TSE bulk processo
    data the LEGACY_TRE_DIARIOS script cleans, but the two outputs are not
    drop-in-equivalent (classe transform, assunto1..4 split, dedup). See
    `docs/decisions.md` 2026-05-26 entry for the schema diff and the
    migration recipe. Live consumer:
    `projects/REDACTED-PROJECT/source/query/proc__tse.py`.
  - created: 2026-05-26
