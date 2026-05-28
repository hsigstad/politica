# Decisions

## 2026-05-27 — Recover 2024 candidate status from `consulta_cand_complementar`

**Decision:** When `DS_DETALHE_SITUACAO_CAND` is missing or all-`#NE` in
the main `consulta_cand` file (2024 onwards), read `DS_SITUACAO_JULGAMENTO`
from the companion `consulta_cand_complementar` file and join on
`SQ_CANDIDATO`. The complementar file only exists for 2024; the guard is
a no-op for earlier years. Implemented in
`candidato_politico.py:get_candidates()`, lines 393–419.

**Reason:** TSE split several columns out of the main `consulta_cand`
file in 2024. `DS_DETALHE_SITUACAO_CAND` (deferido / indeferido / ...)
was removed entirely, while `DS_SITUACAO_CANDIDATURA` was redacted to
`#NE`. The replacement column `DS_SITUACAO_JULGAMENTO` lives in
`consulta_cand_complementar_2024_<state>.csv`, with 100% SQ_CANDIDATO
join coverage.

**Verified results (2026-05-27):** 2024 status coverage = 100.0% (up from
0.0%). 2020 status coverage remains 100.0% (no regression). Status
vocabulary is compatible with 2020 — the top values are DEFERIDO (454,806),
INDEFERIDO (10,381), RENUNCIA (9,167), consistent with prior years.

**Vocabulary changes in 2024** (noted for downstream consumers):
- `INDEFERIDO EM PRAZO RECURSAL OU COM RECURSO` (522) replaces 2022's
  `INDEFERIDO COM RECURSO`. Functionally equivalent — downstream
  consumers that set-match on `INDEFERIDO COM RECURSO` (e.g.
  `DOWNSTREAM_PROJECT:INELIGIBLE_STATUSES`)
  should add the new form.
- `AGUARDANDO JULGAMENTO` (16) — new, functionally equivalent to
  `PENDENTE DE JULGAMENTO`. Downstream consumers that match on the
  latter should add this form.
- `PEDIDO NAO CONHECIDO EM PRAZO RECURSAL OU COM RECURSO` (7) — new,
  analogous to `PEDIDO NAO CONHECIDO`.
- `FALECIMENTO` (162) replaces `FALECIDO`. Neither appears in DOWNSTREAM_PROJECT's
  eligibility sets (dead candidates do not re-run).

## 2026-05-26 — Row-level CPF recovery for 2024 (Bug 1 in `candidato_politico.py`)

**Decision:** Replace the state-level `.all()` guard on the 2024 titulo→CPF
recovery in `get_candidates()` with a row-level coalesce: attempt recovery
on any state file containing at least one sentinel CPF, and only overwrite
the rows whose CPF is in `{-1, -4, -5, '', 'nan', '0'}`. Idempotent for
pre-2024 years (sentinel mask is empty).

**Reason:** Audit of the built `candidato.csv` showed 2024 CPF coverage
of only 11.8% (vs ~100% in 2008-2020). Per-state breakdown revealed
recovery fired only for SP/MG/RJ/BA (where the raw `NR_CPF_CANDIDATO`
column was uniformly sentinel) and silently skipped the other 23 states
because at least one non-sentinel value in their raw column caused the
prior `cpf_col.isin(['-1','-4','-5']).all()` guard to return False.
Titulo crosswalk match potential in those skipped states was 20-50%.

A second bug (Bug 1b) was discovered during verification: `get_candidates()`
reads the raw CSV without `dtype=str`, so pandas casts
`NR_TITULO_ELEITORAL_CANDIDATO` to `int64`, stripping leading zeros. The
crosswalk was built with `dtype=str`, preserving them. The titulo join
silently failed for any titulo starting with zero — which is most titulos
outside SP/MG/RJ/BA. Fix: `.str.zfill(12)` applied to both the crosswalk
build (line 30) and the titulo key in `get_candidates()` (line 384).

**Verified results (2026-05-26):** 2024 CPF coverage = 49.6% (up from 11.8%
pre-fix). 2020-elected → 2024 match = 79.0% (up from 17.8%). 2020 CPF
coverage remains 100.0% (no regression). Both metrics exceed the original
targets (37% / 62%).

**Outstanding issues** (logged in todo.md):
- 2024 `status` column is 100% empty — TSE either renamed or also
  redacted `DS_DETALHE_SITUACAO_CAND`.

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
