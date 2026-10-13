# INTENT: register every politica clean table (and the source-channel cards)
# the empirical sitekit archetype renders as a browsable data portal.
# REASONING: politica cleans TSE open data into ~15 relational tables across
# five domains (candidates/people, election results, party organization,
# sanctions/manifestos, opinion polls). The portal shows one page per table —
# columns, grain check, example rows, coverage-by-year — so downstream repos
# (notably ficha) can cross-link to politica's clean outputs instead of
# re-documenting them. Prose lives HERE (description/source_notes), not in a
# per-heading docs/data.md, matching govspend's empirical-archetype wiring.
# ASSUMES: compute.py reads path (CSV or parquet, branched on suffix),
# categorical/temporal/key/mask columns; every dataset.category belongs to
# exactly one SourceConfig.categories entry. source_script must exist (its
# rendered page backs the per-dataset "Source:" link).
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
CLEAN = PROJECT_ROOT / "build" / "clean"

# Cache dir for per-dataset summary JSONs. Committed to git (it sits outside the
# gitignored build/) so the site builds on a machine without the clean tables.
# summary/build_all.py writes here; the site's empirical archetype reads here.
CACHE_DIR = Path(__file__).parent / "cache"


@dataclass
class SourceConfig:
    """A landing-page source card. Aggregates datasets via `categories`."""
    id: str
    name: str
    description: str
    categories: list[str]


@dataclass
class DatasetConfig:
    """One cleaned politica table (CSV or parquet)."""
    id: str                              # slug; cache file + page url
    name: str                            # short display label
    description: str                     # prose shown on the dataset page
    path: Path                           # build/clean file (CSV or parquet)
    category: str                        # exactly one SourceConfig.categories entry
    source_script: str                   # repo-relative builder (its page backs "Source:")
    grain: str                           # one-line row-grain description
    layer: str = "clean"
    source_notes: str = ""
    categorical_columns: list[str] = field(default_factory=list)
    temporal_columns: list[str] = field(default_factory=list)
    # Declared unique key. When set, compute.py's verify_grain confirms it and
    # the page shows a green check / red cross badge.
    key_columns: list[str] | None = None
    # Person-level PII columns (CPF, titulo eleitoral) blanked to [redacted] in
    # example values and sample rows. politica is a PUBLIC repo; individual CPFs
    # and voter-registration numbers are never surfaced. Aggregate charts
    # (temporal histograms) are computed from the raw column before masking.
    mask_columns: list[str] = field(default_factory=list)
    pseudocode: str | None = None
    flagship: bool = False


# ── Source cards (one per domain) ─────────────────────────────────────────────
SOURCES: list[SourceConfig] = [
    SourceConfig(
        "electoral", "Candidates, people & results",
        "The electoral spine: every candidacy (candidato), the deduplicated "
        "person registry (politico), aggregated election results (eleicao), and "
        "geocoded polling places (local_votacao). Built from the TSE "
        "consulta_cand, votacao and local-votacao bulk datasets, 1998–2024.",
        ["Candidates & people", "Elections & results"],
    ),
    SourceConfig(
        "party", "Party organization",
        "Party structure and membership from the TSE party datasets: directory "
        "organs and their members (orgao_partidario), credentialed delegates "
        "(delegado_partidario), and the monthly membership profile counts "
        "(perfil_filiacao_partidaria).",
        ["Party organization"],
    ),
    SourceConfig(
        "sanctions", "Sanctions & manifestos",
        "Candidacy-rejection reasons from the electoral courts "
        "(motivo_cassacao) and the full text of mayoral government plans filed "
        "with each candidacy (proposta_governo).",
        ["Sanctions & manifestos"],
    ),
    SourceConfig(
        "polls", "Opinion polls",
        "TSE-registered opinion polls: the 2020 and 2024 mayoral-poll "
        "registrations (poll_2020, poll_2024), the per-candidate vote "
        "intentions extracted from the 2020 and 2024 relatórios "
        "(poll_response_2020, poll_response_2024), and the pollingdata.com.br "
        "president/governor archive (poll_response_pollingdata).",
        ["Opinion polls"],
    ),
]


# ── shorthand ─────────────────────────────────────────────────────────────────
def ds(id, name, desc, path, category, source_script, grain, **kw):
    return DatasetConfig(id=id, name=name, description=desc, path=path,
                         category=category, source_script=source_script,
                         grain=grain, **kw)


DATASETS: list[DatasetConfig] = [
    # ── Candidates & people ──────────────────────────────────────────────────
    ds(
        "candidato", "candidato — candidacy panel",
        "One row per candidate-election appearance across every TSE cycle "
        "1998–2024 (all offices, both rounds). Carries the person key "
        "(politico_id), party/coalition, office, geography (municipio_id, "
        "estado, ibge7), electoral outcome (votes, elected, margin), and "
        "candidate attributes (education, occupation, marital_status). This is "
        "politica's single biggest external dependency — ficha's cand table and "
        "the whole electoral spine are built from it.",
        CLEAN / "candidato.csv", "Candidates & people",
        "source/clean/candidato_politico.py",
        "One row per candidacy — (politico_id, year, round, office, "
        "municipio_id); municipio_id is null for non-municipal offices, and a "
        "handful of TSE duplicate candidacies remain.",
        key_columns=["politico_id", "year", "round", "office", "municipio_id"],
        categorical_columns=["office", "party", "estado", "round", "status",
                             "elected", "electeddummy", "education",
                             "marital_status", "occupation", "suplementar"],
        temporal_columns=["year"],
        mask_columns=["cpf", "politico_id", "titulo"],
        flagship=True,
    ),
    ds(
        "politico", "politico — deduplicated person registry",
        "One row per person (politico_id), deduplicated across all cycles "
        "keeping the first occurrence. Carries birthplace (birth_municipio, "
        "birth_estado), demographics (gender, race, nationality, birthdate), and "
        "the titulo/CPF basis of the person key. politico_id is CPF when "
        "available, else 'T' + titulo eleitoral (see docs/data.md).",
        CLEAN / "politico.csv", "Candidates & people",
        "source/clean/candidato_politico.py",
        "One row per politico_id.",
        key_columns=["politico_id"],
        categorical_columns=["gender", "race", "nationality", "birth_estado"],
        temporal_columns=["birthdate"],
        mask_columns=["cpf", "politico_id", "titulo", "birthdate"],
    ),
    # ── Elections & results ──────────────────────────────────────────────────
    ds(
        "eleicao", "eleicao — aggregated election results",
        "Municipality/election-level turnout and vote totals: eligible voters "
        "(aptos), turnout (comparecimento), abstentions, and nominal/legend/"
        "blank/null vote counts per (year, round, office, electoral unit).",
        CLEAN / "eleicao.csv", "Elections & results",
        "source/clean/eleicao.py",
        "One row per aggregated result unit (year × round × office × electoral "
        "unit × abrangência).",
        categorical_columns=["office", "estado", "round", "tp_abrangencia",
                             "suplementar"],
        temporal_columns=["year"],
    ),
    ds(
        "local_votacao", "local_votacao — geocoded polling places",
        "Polling-place registry with address and geocoordinates: one row per "
        "polling location per election year, carrying município, zona, address, "
        "CEP, latitude/longitude and the geocode provenance (coord_source).",
        CLEAN / "local_votacao.parquet", "Elections & results",
        "source/clean/local_votacao.py",
        "One row per (year, municipio_id, zona, local_votacao).",
        key_columns=["year", "municipio_id", "zona", "local_votacao"],
        categorical_columns=["estado", "coord_source", "year"],
        temporal_columns=["year"],
    ),
    # ── Party organization ───────────────────────────────────────────────────
    ds(
        "orgao_partidario", "orgao_partidario — party directory organs & members",
        "Party directory organs (national/state/municipal) and their members: "
        "one row per (organ, member), carrying party, scope (abrangencia), "
        "geography, the member's role (cargo), term dates and status.",
        CLEAN / "orgao_partidario.parquet", "Party organization",
        "source/clean/orgao_partidario.py",
        "One row per (organ, member, role) — a member holding several roles in "
        "an organ appears once per role.",
        categorical_columns=["partido", "tipo_orgao", "abrangencia", "estado",
                             "cargo", "genero", "situacao_membro",
                             "situacao_orgao"],
        temporal_columns=["dt_inicio_orgao"],
        mask_columns=["titulo_eleitoral"],
    ),
    ds(
        "delegado_partidario", "delegado_partidario — credentialed party delegates",
        "Party delegates credentialed before the electoral courts: one row per "
        "delegate credential, with party, scope, electoral unit and the "
        "credentialing/de-credentialing dates.",
        CLEAN / "delegado_partidario.parquet", "Party organization",
        "source/clean/delegado_partidario.py",
        "One row per sq_delegado.",
        key_columns=["sq_delegado"],
        categorical_columns=["partido", "abrangencia", "estado"],
        temporal_columns=["dt_credenciamento"],
        mask_columns=["titulo_eleitoral"],
    ),
    ds(
        "perfil_filiacao_partidaria", "perfil_filiacao_partidaria — membership profile",
        "Aggregated party-membership counts by month and cell: filiados per "
        "(ano_mes, party, município, zona) broken down by gender, age band, "
        "education, occupation and race. No person-level rows — counts only.",
        CLEAN / "perfil_filiacao_partidaria.parquet", "Party organization",
        "source/clean/perfil_filiacao_partidaria.py",
        "One row per (ano_mes, party, municipio_id, zona, demographic cell).",
        categorical_columns=["partido", "estado", "genero", "faixa_etaria",
                             "escolaridade", "raca", "ocupacao", "ano_mes"],
        temporal_columns=[],
    ),
    # ── Sanctions & manifestos ───────────────────────────────────────────────
    ds(
        "motivo_cassacao", "motivo_cassacao — candidacy rejection reasons",
        "Reasons a candidacy was rejected/annulled by the electoral courts: one "
        "row per (candidacy, reason), with the reason text, its type, the "
        "related process number and geography.",
        CLEAN / "motivo_cassacao.csv", "Sanctions & manifestos",
        "source/clean/motivo_cassacao.py",
        "One row per (year, estado, SQ_CANDIDATO, motivo).",
        categorical_columns=["motivo", "tipo_motivo", "estado", "eleicao"],
        temporal_columns=["year"],
    ),
    ds(
        "proposta_governo", "proposta_governo — mayoral government plans",
        "Full text of every mayoral candidate's proposta de governo (manifesto), "
        "legally required at candidacy registration. One row per (year, estado, "
        "SQ_CANDIDATO); joins candidato on (year, estado, SQ_CANDIDATO). Covers "
        "2012, 2016, 2020, 2024 (~65k plans); ~9,300 are image-only scans "
        "awaiting OCR (text_source).",
        CLEAN / "proposta_governo.parquet", "Sanctions & manifestos",
        "source/clean/proposta_governo.py",
        "One row per (year, estado, SQ_CANDIDATO).",
        key_columns=["year", "estado", "SQ_CANDIDATO"],
        categorical_columns=["estado", "year", "text_source", "n_docs"],
        temporal_columns=["year"],
    ),
    # ── Opinion polls ────────────────────────────────────────────────────────
    ds(
        "poll_2020", "poll_2020 — 2020 mayoral poll registrations",
        "TSE-registered 2020 mayoral opinion polls: one row per protocol, with "
        "the contracting institute, município, registration/disclosure dates, "
        "sample size and declared value.",
        CLEAN / "poll_2020.parquet", "Opinion polls",
        "source/clean/poll.py",
        "One row per protocol.",
        key_columns=["protocol"],
        categorical_columns=["cargo", "uf", "institute", "st_pesquisa_propria"],
        temporal_columns=["date_registered", "date_disclosed"],
    ),
    ds(
        "poll_2024", "poll_2024 — 2024 mayoral poll registrations",
        "TSE-registered 2024 mayoral opinion polls: one row per protocol, same "
        "schema as poll_2020 (institute, município, dates, sample size, value).",
        CLEAN / "poll_2024.parquet", "Opinion polls",
        "source/clean/poll.py",
        "One row per protocol.",
        key_columns=["protocol"],
        categorical_columns=["cargo", "uf", "institute", "st_pesquisa_propria"],
        temporal_columns=["date_registered", "date_disclosed"],
    ),
    ds(
        "poll_response_2020", "poll_response_2020 — 2020 poll vote intentions",
        "Per-candidate vote intentions from the 2020 mayoral polls: one row per "
        "(poll, round, candidate), with the reported value and the share among "
        "real (non-aggregate) candidates (percent_on_real).",
        CLEAN / "poll_response_2020.parquet", "Opinion polls",
        "source/clean/poll_response_2020.py",
        "One row per (poll, round, candidate).",
        categorical_columns=["uf", "round", "row_type", "instituto_poll"],
        temporal_columns=["data_poll"],
    ),
    ds(
        "poll_response_2024", "poll_response_2024 — 2024 poll vote intentions",
        "Per-candidate vote intentions extracted by LLM from the 2024 mayoral "
        "relatório PDFs, joined to the registration and the TSE candidate "
        "registry: one row per (candidate × scenario × poll), 149,934 rows from "
        "~8,169 polls. Carries scenario_type, reported percent, and the matched "
        "candidate (cand_politico_id, match_method).",
        CLEAN / "poll_response_2024.parquet", "Opinion polls",
        "source/clean/poll_response_2024.py",
        "One row per (protocol, scenario, candidate).",
        categorical_columns=["scenario_type", "uf", "party", "cargo",
                             "institute", "match_method"],
        temporal_columns=["date_start", "date_registered"],
        mask_columns=["cand_cpf", "cand_politico_id"],
    ),
    ds(
        "poll_response_pollingdata", "poll_response_pollingdata — president/governor polls",
        "President/governor/senate vote intentions from the pollingdata.com.br "
        "archive (2018, 2022): one row per (election, poll, scenario, "
        "candidate), joinable to the TSE poll registry on protocolo.",
        CLEAN / "poll_response_pollingdata.parquet", "Opinion polls",
        "source/clean/poll_response_pollingdata.py",
        "One row per (election, poll, cenario, candidate).",
        categorical_columns=["office", "uf", "turno", "institute",
                             "is_aggregate", "cargo_raw"],
        temporal_columns=["poll_date", "year"],
    ),
]

SOURCE_BY_ID = {s.id: s for s in SOURCES}
DATASET_BY_ID = {d.id: d for d in DATASETS}
