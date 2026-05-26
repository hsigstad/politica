# Decisions

## 2026-05-26 — Defer migration of LEGACY_TRE_DIARIOS `tse_processos.py` to politica

**Decision:** Keep `LEGACY_TRE_DIARIOS` alive
as the 2020 path used by the REDACTED-PROJECT paper build, even though
`pipelines/politica/source/clean/processo.py` now covers the same TSE bulk
processo data (and additionally covers 2024). Use politica's `processo.csv`
for 2024+ work only; do not repoint `projects/REDACTED-PROJECT/source/query/proc__tse.py`
to politica until the schema-translation work below is done and verified.

**Reason:** The two cleaning paths produce non-equivalent outputs, so a
drop-in repoint of `proc__tse.py` would break downstream R tables. Three
material differences between `LEGACY_TRE_DIARIOS`
(2020) and `politica/build/clean/processo.csv` (2020 slice):

1. **`classe` values.** LEGACY_TRE_DIARIOS applies `clean_classe` +
   `diarios.clean.transform` on `DS_CLASSE` to produce sigla form preserving
   case (`Pet`, `Rp`, `AIJE`, `PC`, ...), plus manual overrides
   ("PRESTACAO DE CONTAS ELEITORAIS" → "PC", "REPRESENTACAO ESPECIAL" → "Rp",
   "PETICAO CIVEL" → "Pet"). Politica keeps `classe_sigla` (raw `SG_CLASSE`,
   all-caps: `PETCIV`, `RP`, `AIJE`) plus the full `classe` (DS_CLASSE post
   `clean_text_columns`, all-caps no accents). The R tables filter on
   `classe_inicial.isin(["AIJE","Rp","AIME"])` — the "Rp" match would break
   on case alone, and the manual overrides are absent.
2. **`assunto1..4` is unrecoverable from politica's output.** LEGACY_TRE_DIARIOS
   splits `DS_ASSUNTO_PRINCIPAL` on " - " into four case-preserving columns.
   Politica concatenates the string and runs it through `clean_text_columns`,
   destroying the " - " separator. Rebuilding the split from politica's
   output is impossible.
3. **11-row count gap.** LEGACY_TRE_DIARIOS applies
   `drop_duplicates(['number','instancia'])` removing 11 rows it documents
   as "looks like errors". Politica does not dedupe.

Plus minor differences in `tribunal` (`TRE-MA` vs `TREMA`),
`tipo_distribuicao` (`Por sorteio` vs `POR SORTEIO`), and `judge_title` case.

**Reason for keeping the duplication:** The REDACTED-PROJECT paper is at
a sensitive stage. `git diff HEAD -- build/` is currently empty —
tables and figures on this server reproduce the laptop commit byte-for-byte.
A repoint risks regressing those outputs right before submission, for no
near-term gain. The duplication is one extra script in LEGACY_TRE_DIARIOS per
publication year, tolerable.

**To unlock the migration later (post-acceptance):**

- Change politica's `processo.py` to exclude `assunto` from
  `clean_text_columns` (preserve case + " - " separator); add a dedup pass
  matching LEGACY_TRE_DIARIOS's. This change also forces a sweep of
  `cassacao_2024.py`/`proc_2024.py` keyword constants which currently match
  the cleaned uppercase form.
- Add a sigla-transform step in `proc__tse.py` mirroring LEGACY_TRE_DIARIOS's
  `clean_classe` + `diarios.clean.transform("classe","classe_sigla")`, with
  the manual overrides.
- Run scons on the legacy-pilot build, byte-diff `build/merge/proc.csv` and all
  `build/table/*.tex` against the commit at migration time. Only proceed if
  identical.
- Then delete `LEGACY_TRE_DIARIOS` and its
  build outputs.

**Alternatives considered:**
- Repoint `proc__tse.py` now with on-the-fly classe transform — rejected:
  doesn't address the `assunto1..4` loss and risks subtle row-count drift.
- Modify politica's `processo.py` immediately to preserve assunto structure
  — rejected: breaks the existing `cassacao_2024.py` keyword logic and
  requires a coordinated update; not session-sized.
