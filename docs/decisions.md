# Decisions

## 2026-10-20 — poll_bairro_detail v2→v3: strip inferred coverage/rural, then collapse to one raw `units` row list

**Decision:** Before the (unscaled) bairro universe run, (v2) drop the four
LLM-inferred fields from `poll_bairro_detail` — `coverage_class_resolved`,
`coverage_class_evidence`, `rural_included`, `rural_explicit` (and the
now-orphaned `CoverageClassResolved` enum); then (v3) replace the
two-parallel-field design (`bairros` names list + lossy 10-item
`setor_codes_sample` + `n_bairros_total`/`n_setores_total`/
`distritos_listed`/`regional_structure`) with ONE faithful list, `units`:
one `CoverageUnit` per distinct geographic allocation unit the PDF prints,
each carrying whatever identifiers that row shows (`name` / `setor_code` /
`distrito` / `n_entrevistas`). Final v3 shape: `pesquisa_realized`, `units`,
`n_units_total`, `total_interviews_distributed`, `extraction_notes`. Schema
v1 → v3.

**Why v3 on top of v2:** v2 still violated "extract what is in the raw, no
more no less" in two ways — `setor_codes_sample` was a lossy 10-item
*sample* (with the real count hidden in `n_setores_total`), and splitting
names from codes into parallel lists destroyed the row-level
name↔setor↔count linkage. The single `units` grain preserves the linkage,
drops nothing (cap raised to 80 with a truncation-proof `n_units_total`),
and lets `distritos_listed` / `regional_structure` go (both derivable from
the units). One judgment call: for per-interview setor microdata the model
dedups to one unit per DISTINCT setor with its interview count, rather than
transcribing one row per interview — still the raw allocation, not an
inference. The prompt instructs ALWAYS capturing IBGE setor codes when
printed (the deterministic urban/rural key downstream).

**Why:** same extract-raw-derive-downstream principle as the questionnaire
v2 rework. Coverage class and rural inclusion were inferred from bairro
NAME STRINGS — subjective and hard to audit. They are better derived
downstream, grounded in real geography: matched IBGE setor `situacao`
(urbano/rural) + an electorate-coverage ratio (sampled-bairro electorate /
município electorate), reusing the bairro→seção→electorate join. If a rural
guess is ever wanted for name-only PDFs, that is a SEPARATE optional
downstream LLM pass, deliberately NOT baked into this extraction.

**Consumers:** the only consumer of the dropped fields is poll-sponsor-bias
(`curated_pairs_assemble.py`, `pilot_bairro_detail.py`,
`_secao_oversampling_scope.py`, AN-107 coverage mechanism). politica itself
has no clean/assembly consumer of `bairro_detail`. The poll-sponsor-bias
session owns rebuilding the downstream coverage derivation (setor situacao
+ electorate ratio, consuming territorio read-only) so stripping the
extractor does not strand AN-107.

**Touched files:** `source/llm/schemas.py`,
`source/llm/prompts/poll_bairro_detail_{system,user}.txt`. The worked-
example page's bairro section (`source/site/worked_example/bairro_detail.json`)
still shows the v1 shape until the bairro extractor is re-run.

## 2026-10-20 — Scenario-type vocabulary is fragmented across three poll extractions (crosswalk + forward plan)

**Decision:** Do NOT re-extract already-scaled tasks to harmonize the
scenario/question-type vocabulary. `poll_relatorio` ran on the universe
(`build/llm/poll_relatorio_2024.parquet`) and `poll_coverage` ran on the
full 14,876-poll universe, so under the freeze rule (never touch a prompt
already run on the universe) their schemas stay as-is. Instead we record
the crosswalk here and adopt a single canonical vocabulary only in (a)
not-yet-scaled tasks going forward and (b) `poll_relatorio` *if and when*
it is re-extracted for an independent reason.

**Why:** The same concept (a vote-intention / approval / rejection
scenario) is encoded three incompatible ways, which forces any
cross-task consumer to hand-reconcile:

- `poll_questionario.QuestionType` (enum): `estimulada`, `espontanea`,
  `avaliacao`, `rejeicao`, `party`, `demographic`, `issue`, `screener`,
  `other`, `unclear`. Source: questionnaire PDF (actual instrument).
- `poll_operations.ScenarioType` (enum): `estimulado`, `espontaneo`,
  `segundo_turno`, `rejeicao`, `avaliacao_governo`, `votos_validos`,
  `rejeicao_estimulada`, `other`. Source: DS_METODOLOGIA narrative.
- `poll_relatorio.Scenario.scenario_type` (FREE STRING — drift risk):
  `espontaneo`, `estimulado`, `votos_validos`, `rejeicao`,
  `avaliacao_governo`, `segundo_turno_simulacao`, `outro`. Source:
  relatório PDF (reported numbers). **This one is frozen.**

Spelling (`estimulada`/`estimulado`), granularity, and the free-string
form all differ. The vocabularies also carve approval differently:
questionnaire `avaliacao` is candidate/incumbent approval in general,
whereas operations/relatório split out `avaliacao_governo` (government
approval) specifically — a consumer merging them must treat
`avaliacao` as the superset. Questionnaire has no `segundo_turno` type:
a second-round estimulada is just another `estimulada` block.

**Canonical crosswalk** (target vocabulary ← each source's values):

| canonical | questionario | operations | relatorio (frozen) |
|---|---|---|---|
| `estimulada` (closed-list vote intention) | estimulada | estimulado | estimulado |
| `espontanea` (open vote intention) | espontanea | espontaneo | espontaneo |
| `segundo_turno` | (an estimulada block) | segundo_turno | segundo_turno_simulacao |
| `rejeicao` | rejeicao | rejeicao / rejeicao_estimulada | rejeicao |
| `avaliacao_candidato` | avaliacao (superset) | — | — |
| `avaliacao_governo` | avaliacao (superset) | avaliacao_governo | avaliacao_governo |
| `votos_validos` | (derived from a scenario) | votos_validos | votos_validos |
| `party` | party | — | — |
| `demographic`/`issue`/`screener` | demographic/issue/screener | — | — |
| `other`/`unclear` | other/unclear | other | outro |

**Forward plan (no re-extraction now):**

- Consumers joining across tasks map through the table above; treat
  questionnaire `avaliacao` as `{avaliacao_candidato, avaliacao_governo}`.
- A shared `ScenarioType` enum is NOT introduced as code yet because the
  only free-string offender (`poll_relatorio`) is frozen; `questionario`
  and `operations` already use enums. When `poll_relatorio` is next
  re-run, enum-ify `scenario_type` against the canonical column and the
  harmonization lands for free.

**Touched files:** none (documentation only; crosswalk is advisory for
downstream consumers).

## 2026-05-28 — Poll pipeline (scrape + LLM extract + clean) consolidated here

**Decision:** The TSE poll acquisition + cleaning chain lives here in
`source/{scrape,llm,clean}/`. Project-specific assembly steps (e.g.
muni-day panels) stay in the downstream analysis repositories.

**Why:** More than one downstream analysis needs the cleaned poll
table. Cleaned polls are project-neutral political data — same shape
as candidato.csv, processo.csv, etc., already here — so they belong in
shared pipeline infrastructure.

**Touched files:**

- `source/scrape/tse_relatorio.py` — new (moved). Reads TSE poll
  registration CSVs from `path.tse_polls_2024_dir` (currently
  `build/scrape/tse_polls_2024/`); writes PDFs to
  `build/scrape/tse_relatorio/{year}/`.
- `source/llm/poll_extract.py` — new (moved). Reads PDFs from
  `path.build_scrape_dir`; writes per-protocol JSON + combined
  parquet to `path.build_llm_dir`.
- `source/clean/poll_response_2024.py` — new (moved; renamed from
  `poll_2024.py` 2026-06-17 to reflect candidate-scenario grain).
  Reads LLM extractions + TSE registration CSVs; writes
  `build/clean/poll_response_2024.parquet`.
- `path.py` — added `BUILD_DIR`, `build_scrape_dir`, `build_llm_dir`,
  `build_clean_dir`, `tse_polls_2024_dir` (so consumers don't have
  to hard-code paths).

**Open caveat (intentional, time-bounded):** the 2024 poll
registration CSVs and PDFs are staged under `build/scrape/` rather than
the canonical `$DATA_DIR`. This is workspace-local staging for
convenience. Migrate to `$DATA_DIR` once the SP-slice pilot is stable —
one-line edit to `path.tse_polls_2024_dir`.

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
  consumers that set-match on `INDEFERIDO COM RECURSO` should add the
  new form.
- `AGUARDANDO JULGAMENTO` (16) — new, functionally equivalent to
  `PENDENTE DE JULGAMENTO`. Downstream consumers that match on the
  latter should add this form.
- `PEDIDO NAO CONHECIDO EM PRAZO RECURSAL OU COM RECURSO` (7) — new,
  analogous to `PEDIDO NAO CONHECIDO`.
- `FALECIMENTO` (162) replaces `FALECIDO`. Neither appears in typical
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

## 2026-05-26 — Defer retiring the legacy TRE-diários processo cleaning path

**Decision:** Keep the legacy TRE-diários `processo` cleaning path alive
for 2020 work, even though this pipeline's `source/clean/processo.py` now
covers the same TSE bulk processo data (and additionally covers 2024).
Use `processo.csv` for 2024+ work only; do not repoint the legacy
consumer to it until the schema-translation work below is done and
verified.

**Reason:** The two cleaning paths produce non-equivalent outputs, so a
drop-in repoint would break downstream tables. Three material
differences between the legacy `tse_proc_instancia.csv` (2020) and this
pipeline's `processo.csv` (2020 slice):

1. **`classe` values.** The legacy path applies `clean_classe` +
   `diarios.clean.transform` on `DS_CLASSE` to produce sigla form
   preserving case (`Pet`, `Rp`, `AIJE`, `PC`, ...), plus manual
   overrides ("PRESTACAO DE CONTAS ELEITORAIS" → "PC", "REPRESENTACAO
   ESPECIAL" → "Rp", "PETICAO CIVEL" → "Pet"). This pipeline keeps
   `classe_sigla` (raw `SG_CLASSE`, all-caps: `PETCIV`, `RP`, `AIJE`)
   plus the full `classe` (DS_CLASSE post `clean_text_columns`, all-caps
   no accents). Downstream tables filtering on
   `classe_inicial.isin(["AIJE","Rp","AIME"])` would break on case
   alone, and the manual overrides are absent.
2. **`assunto1..4` is unrecoverable from this pipeline's output.** The
   legacy path splits `DS_ASSUNTO_PRINCIPAL` on " - " into four
   case-preserving columns. This pipeline concatenates the string and
   runs it through `clean_text_columns`, destroying the " - " separator.
   Rebuilding the split is impossible.
3. **11-row count gap.** The legacy path applies
   `drop_duplicates(['number','instancia'])` removing 11 rows it
   documents as "looks like errors". This pipeline does not dedupe.

Plus minor differences in `tribunal` (`TRE-MA` vs `TREMA`),
`tipo_distribuicao` (`Por sorteio` vs `POR SORTEIO`), and `judge_title`
case.

**Reason for keeping the duplication:** A downstream paper build is at a
sensitive stage and reproduces byte-for-byte against a fixed commit. A
repoint risks regressing those outputs for no near-term gain. The
duplication is one extra legacy script per publication year, tolerable.

**To unlock the migration later:**

- Change `processo.py` to exclude `assunto` from `clean_text_columns`
  (preserve case + " - " separator); add a dedup pass matching the
  legacy path's. This also forces a sweep of the `cassacao`/`proc`
  keyword constants that currently match the cleaned uppercase form.
- Add a sigla-transform step in the consumer mirroring the legacy
  `clean_classe` + `diarios.clean.transform("classe","classe_sigla")`,
  with the manual overrides.
- Rebuild the downstream tables, byte-diff the merged processo output
  and all generated tables against the commit at migration time. Only
  proceed if identical.
- Then delete the legacy cleaning script and its build outputs.

**Alternatives considered:**
- Repoint now with on-the-fly classe transform — rejected: doesn't
  address the `assunto1..4` loss and risks subtle row-count drift.
- Modify `processo.py` immediately to preserve assunto structure —
  rejected: breaks the existing keyword logic and requires a coordinated
  update; not session-sized.
