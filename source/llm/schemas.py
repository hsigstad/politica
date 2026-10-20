# INTENT: define the Pydantic output schemas for every politica LLM extraction
# task; each ExtractionSchema subclass is the authoritative field inventory for
# one system/user prompt pair under source/llm/prompts/ and one extractor module.
# REASONING: keeping the schemas in one module lets llmkit validate structured
# output per task and lets the site render a single schema source page.
# ASSUMES: llmkit.ExtractionSchema provides the base (schema_name/version ClassVars).
"""Pydantic schemas for politica LLM extractions.

Tasks:
  - poll_relatorio: per-candidate vote intentions from TSE-registered poll
    relatório PDFs.
  - poll_lawsuit: alleged-bias dimensions + outcome from electoral-justice
    decisions tagged PESQUISA ELEITORAL (poll-lawsuit sentencas in the
    TRE-diários mov.text join).
  - poll_sampling / poll_coverage / poll_operations: the three-task split
    of poll-methodology extraction from the four DS_* free-text fields of
    the TSE PesqEle registry. See docs/design_levers.md for what each
    extracted field is intended to populate downstream.
"""
from __future__ import annotations

from enum import Enum
from typing import ClassVar, Optional

from pydantic import BaseModel, Field

from llmkit import ExtractionSchema


class CandidateResult(BaseModel):
    candidate_name: str = Field(
        description=(
            "Candidate display name. For aggregate rows like 'Branco/Nulo' "
            "or 'Não sabe', use a descriptive label."
        )
    )
    party: Optional[str] = Field(
        default=None,
        description=(
            "Party abbreviation if shown next to the name (e.g., 'PL', 'PT'). "
            "null if absent or aggregate row."
        ),
    )
    percent: float = Field(
        description="Vote intention percentage in this scenario, 0-100."
    )


class Scenario(BaseModel):
    scenario_type: str = Field(
        description=(
            "One of: 'espontaneo', 'estimulado', 'votos_validos', "
            "'rejeicao', 'avaliacao_governo', 'segundo_turno_simulacao', "
            "'outro'."
        )
    )
    scenario_label: str = Field(description="The exact label used in the PDF.")
    candidates: list[CandidateResult]


class PollRelatorio(ExtractionSchema):
    """Per-candidate vote intentions for ONE registered TSE poll."""
    schema_name: ClassVar[str] = "poll_relatorio"
    schema_version: ClassVar[str] = "v1"

    tse_protocol: str = Field(
        description=(
            "TSE registration number, format 'XX-NNNNN/YYYY'. Echo from "
            "the PDF for join-back validation."
        )
    )
    scenarios: list[Scenario] = Field(
        default_factory=list,
        description=(
            "All voting-intention scenarios for THIS poll (do not include "
            "historical comparison values from previous waves)."
        ),
    )
    extraction_notes: str = Field(
        default="",
        description="Brief note about any ambiguity or judgment call.",
    )


# ─── poll_lawsuit ────────────────────────────────────────────────────
#
# Extracts alleged bias dimensions + judicial outcome from electoral-
# justice decision text on PESQUISA ELEITORAL cases. The design-lever
# enum mirrors a six-lever menu of poll-design choices; `lever_other_text`
# captures alleged bias dimensions NOT in that menu (this is the
# primary research output — it tells us where the menu is incomplete).

class CaseType(str, Enum):
    """Top-level classification of what the case is actually about.

    Most PESQUISA cases are registration / divulgation violations, not
    methodology bias claims. Filter to {methodology_bias,
    fabrication_allegation, sponsor_concealment} for the design-lever
    analysis."""
    registration_missing = "registration_missing"            # poll not registered with TSE
    registration_late = "registration_late"                  # registered too close to election
    divulgation_violation = "divulgation_violation"          # published without required disclosures, wrong format, banned period
    methodology_bias = "methodology_bias"                    # alleges the design itself biases the result
    fabrication_allegation = "fabrication_allegation"        # alleges numbers don't match the declared methodology
    sponsor_concealment = "sponsor_concealment"              # alleges sponsor identity hidden / mis-declared
    enquete_not_pesquisa = "enquete_not_pesquisa"            # informal Facebook/web "enquete" misrepresented as scientific poll
    defamation = "defamation"                                # poll used as vehicle for defamation, not a methodology claim
    other = "other"
    unclear = "unclear"


class DesignLever(str, Enum):
    """Mirrors docs/design_levers.md § The levers. Use lever_other_text
    for anything alleged that doesn't fit one of these six."""
    coverage_exclusion = "coverage_exclusion"               # geographic frame, urban-only etc
    quota_variables = "quota_variables"                     # which demographic quotas
    population_reference = "population_reference"           # census vs TSE-eligible vs turnout-weighted
    mode = "mode"                                           # in-person vs phone vs online
    question_wording_order = "question_wording_order"       # order effects, scenario choice, priming
    nonresponse_handling = "nonresponse_handling"           # undecided treatment


class Outcome(str, Enum):
    procedente = "procedente"
    parcialmente_procedente = "parcialmente_procedente"
    improcedente = "improcedente"
    extinto_sem_merito = "extinto_sem_merito"               # extinto sem resolução do mérito
    nao_conhecido = "nao_conhecido"
    outro = "outro"
    unclear = "unclear"


class PartyMention(BaseModel):
    name: str = Field(description="Party name as written in the decision.")
    role: str = Field(
        description=(
            "One of: 'pollster', 'sponsor', 'candidate_beneficiary', "
            "'media_outlet', 'plaintiff', 'defendant', 'other'."
        )
    )
    cnpj: Optional[str] = Field(
        default=None,
        description="CNPJ if explicitly stated in the decision, else null.",
    )


class PollLawsuit(ExtractionSchema):
    """Alleged bias dimensions + outcome for ONE electoral-justice
    PESQUISA case.

    v2 (2026-06-02): the 50-case pilot showed that most decisions classify
    as registration_missing / divulgation_violation as the PRIMARY legal
    vehicle, but ~25% carry secondary design-bias allegations that v1
    failed to capture because alleged_levers was gated behind
    methodology_bias case_type. v2 (a) drops that gate — alleged_levers
    is extracted from ANY allegation regardless of primary case_type,
    and (b) adds secondary_case_types for cases that combine claims
    (e.g. registration_missing + sponsor_concealment + methodology_bias).
    """
    schema_name: ClassVar[str] = "poll_lawsuit"
    schema_version: ClassVar[str] = "v2"

    case_type: CaseType = Field(
        description=(
            "PRIMARY legal vehicle of the case — the cause of action the "
            "court actually adjudicates. Registration / divulgation "
            "cases get those buckets even when the petitioner adds "
            "methodology arguments; methodology_bias is reserved for "
            "cases where design bias is itself the cause of action."
        )
    )
    secondary_case_types: list[CaseType] = Field(
        default_factory=list,
        description=(
            "Additional case types the petitioner argues alongside the "
            "primary one. Example: a registration_missing case where "
            "the petition also alleges fabrication_allegation and "
            "methodology_bias. Empty if there is only one claim type. "
            "Do NOT repeat the primary case_type here."
        ),
    )
    case_type_evidence: str = Field(
        default="",
        description=(
            "1-2 sentence quote or paraphrase from the decision text "
            "supporting the case_type choice."
        ),
    )

    alleged_levers: list[DesignLever] = Field(
        default_factory=list,
        description=(
            "Which design-lever menu items the petition alleges as "
            "biased — extract from ANY allegation in the case, "
            "including secondary arguments inside a registration / "
            "divulgation primary case. A case can flag multiple levers. "
            "Empty only when no design-lever allegation appears at all."
        ),
    )
    lever_other_text: str = Field(
        default="",
        description=(
            "ALLEGED bias dimensions that do NOT fit the six-lever menu "
            "above. This is the most important free-text output — it "
            "tells us what's missing from the menu. Examples that would "
            "go here: 'alleged interviewer coaching', 'alleged ballot-"
            "box stuffing of online enquete', 'alleged systematic "
            "exclusion of MDB voters from sample'. Empty string if all "
            "alleged dimensions fit the enum."
        ),
    )

    pollster: Optional[PartyMention] = Field(
        default=None,
        description="Pollster firm named in the case, if any.",
    )
    sponsor: Optional[PartyMention] = Field(
        default=None,
        description=(
            "Poll sponsor (contratante) named in the case, if any. "
            "Often a campaign committee, party, or media outlet."
        ),
    )
    candidate_beneficiary: Optional[PartyMention] = Field(
        default=None,
        description=(
            "Candidate alleged to benefit from the bias, if named "
            "and distinct from the sponsor."
        ),
    )

    outcome: Outcome = Field(description="Judicial outcome.")
    outcome_reason: str = Field(
        default="",
        description=(
            "1-2 sentences on WHY the court ruled this way — especially "
            "useful for methodology_bias cases: did the court find the "
            "design choice substantively biasing, or dismiss on "
            "procedural grounds?"
        ),
    )

    petitioner_role: str = Field(
        default="",
        description=(
            "Brief description of who sued whom: e.g. 'opposing "
            "candidate vs pollster firm', 'MPE vs sponsor', "
            "'party coalition vs media outlet'."
        ),
    )

    extraction_notes: str = Field(
        default="",
        description=(
            "Brief note about ambiguity or judgment calls. Flag here if "
            "the decision text appears truncated or refers to an "
            "earlier ruling whose reasoning we don't see."
        ),
    )


# ─── poll methodology: three-task split ──────────────────────────────
#
# Inputs are the four free-text fields of the TSE PesqEle registry:
#   DS_METODOLOGIA_PESQUISA, DS_PLANO_AMOSTRAL,
#   DS_SISTEMA_CONTROLE, DS_DADO_MUNICIPIO.
#
# Why three tasks instead of one:
#   - quality: smaller schemas keep LLM attention even (no last-field
#     not_specified dump);
#   - cache iteration: refining one task's prompt doesn't invalidate
#     the others;
#   - per-task worked examples: each prompt can carry concrete
#     parsing examples for that task's hard cases.
#
# Boilerplate-score / specificity (group I in design_levers.md) is
# derived deterministically downstream — not an LLM task.

# ── Shared enums ────────────────────────────────────────────────────

class QuotaVariable(str, Enum):
    sex = "sex"
    age = "age"
    education = "education"
    income = "income"
    race = "race"
    religion = "religion"
    occupation = "occupation"
    region = "region"
    other = "other"


# ── poll_sampling: sampling design + sample size + quotas + population ──

class SampleDesignClass(str, Enum):
    simple_random = "simple_random"             # AAS
    stratified = "stratified"                   # stratified random
    quota = "quota"                             # pure quota
    multi_stage = "multi_stage"                 # multi-stage cluster
    ppt = "ppt"                                 # probability proportional to size
    multi_stage_quota = "multi_stage_quota"     # multi-stage cluster + quota at final stage (Brazilian standard)
    mixed = "mixed"
    other = "other"
    not_specified = "not_specified"


class ClusterUnit(str, Enum):
    setor_censitario = "setor_censitario"       # IBGE census tract
    bairro = "bairro"
    zona_eleitoral = "zona_eleitoral"
    secao_eleitoral = "secao_eleitoral"
    district = "district"
    pontos_de_fluxo = "pontos_de_fluxo"         # foot-traffic intercept points
    other = "other"
    none = "none"
    not_specified = "not_specified"


class SelectionWithinCluster(str, Enum):
    random_walk = "random_walk"
    quota = "quota"
    pps = "pps"
    convenience = "convenience"
    mixed = "mixed"
    other = "other"
    not_specified = "not_specified"


class PopulationReference(str, Enum):
    census_2022_residents = "census_2022_residents"
    census_other = "census_other"               # census from year other than 2022
    tse_eligible = "tse_eligible"               # TSE eligible voter file
    turnout_weighted = "turnout_weighted"
    mixed = "mixed"
    other = "other"
    not_specified = "not_specified"


class PopulationSource(str, Enum):
    tse = "tse"
    ibge = "ibge"
    both = "both"
    other = "other"
    not_specified = "not_specified"


class QuotaDistribution(BaseModel):
    """One quota dimension with bin labels and percentages.

    bin_labels and bin_percentages are parallel arrays. bin_counts is
    optional — populate only if absolute counts per bin are stated."""
    variable: QuotaVariable = Field(
        description="Which demographic dimension this quota distribution describes."
    )
    bin_labels: list[str] = Field(
        description=(
            "Exact labels of the bins as written in the text. Examples: "
            "['Masculino', 'Feminino']; "
            "['16 a 24', '25 a 34', '35 a 44', '45 a 59', '60 ou +']; "
            "['Até R$ 2.824,00 (até 2 S.M.)', "
            "'Mais de R$ 2.824,00 a R$ 7.060,00']."
        )
    )
    bin_percentages: list[float] = Field(
        description=(
            "Percent share of each bin (0-100). Parallel to bin_labels. "
            "Example: [50.3, 49.7]. Use empty list if percentages are "
            "not stated."
        )
    )
    bin_counts: list[int] = Field(
        default_factory=list,
        description=(
            "Absolute respondent count per bin if stated. Parallel to "
            "bin_labels. Empty list if not stated. Example: [95, 99, 75, 79, 52]."
        ),
    )


class PollSampling(ExtractionSchema):
    """Sampling design + sample size + quotas + population reference,
    extracted from DS_PLANO_AMOSTRAL + DS_METODOLOGIA_PESQUISA.

    v2: dropped the derivable booleans is_probability_sample (derive from
    sample_design_class / selection_within_cluster) and is_quota_sample
    (derive from quota_distributions non-empty), and quota_variables (the
    quota-dimension set = {d.variable for d in quota_distributions}). The
    dev set confirmed quota_variables is ~99.8% redundant: of 536 polls only
    1 named a quota dimension (income) without printing its bins, and that
    case cannot feed the income-skew lever anyway (no bins → no skew)."""
    schema_name: ClassVar[str] = "poll_sampling"
    schema_version: ClassVar[str] = "v2"

    # A. Sampling design
    sample_design_class: SampleDesignClass = Field(
        description=(
            "Overall sampling design family. multi_stage_quota is the "
            "Brazilian standard (cluster sample of census tracts + "
            "quota selection within); flag distinctly from plain "
            "multi_stage or pure quota."
        )
    )
    sample_design_evidence: str = Field(
        default="",
        description="1-2 sentence quote from the text supporting sample_design_class.",
    )
    n_stages: int = Field(
        default=1,
        description="Number of sampling stages. Use 3 to mean '3 or more'.",
    )
    stage_descriptions: list[str] = Field(
        default_factory=list,
        description=(
            "Brief description of each stage. Example: "
            "['stage 1: PPT selection of setores censitários', "
            "'stage 2: quota selection within setor by sex/age/education/income']."
        ),
    )
    cluster_unit: ClusterUnit = Field(
        description="Primary clustering unit (the unit selected at stage 1)."
    )
    selection_within_cluster: SelectionWithinCluster = Field(
        description="How respondents are picked within the cluster."
    )
    pps_used: bool = Field(
        description="True if probability-proportional-to-size sampling is mentioned anywhere."
    )

    # B. Sample size & precision
    declared_sample_size: Optional[int] = Field(
        default=None,
        description="Declared n. Null if not stated in the text (also available in QT_ENTREVISTADO).",
    )
    margin_of_error_pp: Optional[float] = Field(
        default=None,
        description="Margin of error in percentage points (e.g. 4.9 for ±4.9pp). Null if not stated.",
    )
    confidence_level_pct: Optional[float] = Field(
        default=None,
        description="Confidence level percentage (typically 95). Null if not stated.",
    )
    population_assumed_for_moe: str = Field(
        default="",
        description=(
            "What population assumption underlies the MoE computation, "
            "in 1 short phrase. Example: 'amostra aleatória simples', "
            "'população infinita', 'eleitorado de Feijó AC'."
        ),
    )

    # C. Quotas
    quota_distributions: list[QuotaDistribution] = Field(
        default_factory=list,
        description=(
            "Per-variable distribution. Populate one entry per quota "
            "dimension stated with percentages. Skip dimensions where "
            "only the variable is named without a distribution."
        ),
    )

    # D. Population reference
    population_reference: PopulationReference = Field(
        description=(
            "Which population the quotas are normalized against. "
            "census_2022_residents = IBGE 2022 census resident population; "
            "tse_eligible = TSE eligible-voter file; "
            "turnout_weighted = electorate weighted by expected turnout."
        )
    )
    population_reference_evidence: str = Field(
        default="",
        description="1-2 sentence quote from the text supporting population_reference.",
    )
    population_source: PopulationSource = Field(
        description="Source(s) cited for population statistics."
    )
    census_sectors_used: bool = Field(
        description="True if IBGE setores censitários are explicitly used as clustering or stratification units."
    )
    voter_age_minimum: Optional[int] = Field(
        default=None,
        description="Minimum voter age in the target population (typically 16). Null if not stated.",
    )
    voter_age_maximum: Optional[int] = Field(
        default=None,
        description="Maximum voter age if explicitly capped (rare). Null if no cap.",
    )
    target_population_description: str = Field(
        default="",
        description=(
            "1 short phrase describing the target population. "
            "Example: 'eleitores residentes de Feijó AC ≥16 anos'."
        ),
    )
    references_list: list[str] = Field(
        default_factory=list,
        description=(
            "URLs / table references the text cites (IBGE Sidra, TSE SIG, "
            "panorama do município, etc). Useful for tracking which "
            "pollsters cite which sources."
        ),
    )

    # Meta
    text_truncated: bool = Field(
        default=False,
        description="True if the text appears truncated (hit max_chars cap before sense end).",
    )
    extraction_notes: str = Field(
        default="",
        description="Free-form notes on ambiguity or judgment calls.",
    )


# ── poll_coverage: geographic coverage (single most consequential field) ──

class CoverageClass(str, Enum):
    full_municipality = "full_municipality"
    urban_only = "urban_only"                          # zona urbana
    urban_plus_selected_rural = "urban_plus_selected_rural"
    specific_neighborhoods = "specific_neighborhoods"  # named bairros only
    rural_only = "rural_only"                          # rare
    deferred_complement = "deferred_complement"        # "será complementado" boilerplate (Res 23.600/2019 § 7°)
    other = "other"
    not_specified = "not_specified"


class PollCoverage(ExtractionSchema):
    """Geographic coverage, extracted from DS_DADO_MUNICIPIO (with
    DS_PLANO_AMOSTRAL excerpt when needed). This is the single most
    consequential design field for Channel A — a rural-base candidate's
    sponsor can tilt the result by declaring urban_only coverage."""
    schema_name: ClassVar[str] = "poll_coverage"
    schema_version: ClassVar[str] = "v1"

    coverage_class: CoverageClass = Field(
        description=(
            "The bucket the text falls into. CRITICAL distinction: "
            "deferred_complement is the 'será complementado conforme "
            "Res 23.600/2019 § 7°' pattern where the pollster registered "
            "without committing to a coverage area — code this separately "
            "from not_specified."
        )
    )
    coverage_class_evidence: str = Field(
        default="",
        description="1-2 sentence quote from DS_DADO_MUNICIPIO supporting the class.",
    )

    rural_included: bool = Field(
        description="True if zona rural / assentamentos / districts outside the urban perimeter are stated as included."
    )
    rural_excluded_explicitly: bool = Field(
        description="True only when rural exclusion is stated as a positive choice ('apenas zona urbana')."
    )

    neighborhoods_listed: list[str] = Field(
        default_factory=list,
        description="Explicit list of bairros / districts the text names as covered. Empty if none are named.",
    )
    n_neighborhoods_or_districts: int = Field(
        default=0,
        description="Count of distinct named bairros / districts / setores. 0 if none named.",
    )

    excluded_areas_listed: list[str] = Field(
        default_factory=list,
        description="Areas the text explicitly excludes from coverage. Empty if no exclusions are stated.",
    )

    coverage_to_be_complemented: bool = Field(
        description=(
            "True if the text says the coverage area will be specified "
            "in a later complement (the Res 23.600/2019 § 7° pattern). "
            "Pilot finding: this pattern appears in lawsuit-flagged "
            "polls and is a quality red flag."
        )
    )
    coverage_field_substantive: bool = Field(
        description=(
            "True if the field carries real coverage content. False "
            "if it is only boilerplate / deferred / blank."
        )
    )

    extraction_notes: str = Field(
        default="",
        description="Free-form notes on ambiguity or judgment calls.",
    )


# ── poll_operations: mode + question structure + audit/control ──

class Mode(str, Enum):
    in_person = "in_person"
    phone = "phone"
    online = "online"
    mixed = "mixed"
    not_specified = "not_specified"


class ModeDetails(str, Enum):
    face_to_face_residential = "face_to_face_residential"
    face_to_face_fluxo = "face_to_face_fluxo"           # intercept points
    face_to_face_mixed = "face_to_face_mixed"
    cati = "cati"                                        # phone CATI
    ivr = "ivr"                                          # interactive voice response
    cawi = "cawi"                                        # online self-administered
    rds = "rds"                                          # respondent-driven sampling (rare)
    mixed = "mixed"
    other = "other"
    not_specified = "not_specified"


class CollectionDevice(str, Enum):
    tablet = "tablet"
    smartphone = "smartphone"
    paper = "paper"
    web_form = "web_form"
    mixed = "mixed"
    not_specified = "not_specified"


class ScenarioType(str, Enum):
    espontaneo = "espontaneo"
    estimulado = "estimulado"
    segundo_turno = "segundo_turno"
    rejeicao = "rejeicao"
    avaliacao_governo = "avaliacao_governo"
    votos_validos = "votos_validos"
    rejeicao_estimulada = "rejeicao_estimulada"
    other = "other"


class NonresponseHandling(str, Enum):
    excluded = "excluded"
    redistributed_proportionally = "redistributed_proportionally"
    redistributed_demographic = "redistributed_demographic"
    hold_separate = "hold_separate"
    not_specified = "not_specified"


class AuditMethod(str, Enum):
    in_loco = "in_loco"
    phone = "phone"
    both = "both"
    none = "none"
    other = "other"
    not_specified = "not_specified"


class PollOperations(ExtractionSchema):
    """Mode, question structure, audit and control, extracted from
    DS_METODOLOGIA_PESQUISA + DS_SISTEMA_CONTROLE."""
    schema_name: ClassVar[str] = "poll_operations"
    schema_version: ClassVar[str] = "v1"

    # Mode
    mode: Mode = Field(
        description="Primary mode of data collection."
    )
    mode_details: ModeDetails = Field(
        description=(
            "Sub-flavor of mode. face_to_face_residential = door-to-door "
            "at residences; face_to_face_fluxo = intercept at "
            "foot-traffic points; cati = phone with interviewer; "
            "cawi = online self-administered."
        )
    )
    collection_device: CollectionDevice = Field(
        description="Device used for data capture."
    )
    geolocated: bool = Field(
        description="True if responses are geo-tagged (lat/lon captured)."
    )

    # Question structure
    scenarios_described: list[ScenarioType] = Field(
        default_factory=list,
        description="Vote-intention scenarios mentioned in the methodology."
    )
    question_order_described: bool = Field(
        description="True if the text describes the order of question blocks (approval before vote, etc)."
    )
    name_rotation: bool = Field(
        description="True if the text states candidate-name order is rotated across respondents."
    )
    nonresponse_handling: NonresponseHandling = Field(
        description=(
            "How undecided / refused responses are handled. "
            "Note: this is rarely stated in DS_METODOLOGIA; default to "
            "not_specified unless explicit."
        )
    )

    # Audit / control
    audit_pct: Optional[float] = Field(
        default=None,
        description="Percent of interviews verified post-fieldwork (e.g. 20). Null if not stated.",
    )
    audit_method: AuditMethod = Field(
        description="How completed interviews are verified."
    )
    interviewer_training_described: bool = Field(
        description="True if the text mentions interviewer training (any depth)."
    )
    interviewer_training_details: str = Field(
        default="",
        description="1 short phrase summarizing training described, if any.",
    )
    data_consistency_checks: bool = Field(
        description="True if internal consistency / verification of collected data is mentioned."
    )
    re_contact_verification: bool = Field(
        description="True if re-contacting respondents to verify is mentioned."
    )
    supervisor_role_described: bool = Field(
        description="True if a field supervisor role (separate from interviewer) is described."
    )
    control_measures_other_text: str = Field(
        default="",
        description=(
            "Escape hatch for the fixed audit/control booleans above: "
            "any quality-control or fieldwork-integrity measure the text "
            "describes that does NOT fit training / consistency-check / "
            "re-contact / supervisor / audit-pct. Verbatim or close "
            "paraphrase, Portuguese. Examples: GPS/photo proof of "
            "interview, biometric interviewer check-in, double data "
            "entry, third-party certification/ISO, call-center recording "
            "review. Empty when every described measure fits a boolean. "
            "This keeps the raw control detail for consumers whose "
            "question the boolean menu doesn't anticipate."
        ),
    )

    # Funding mention (cross-task — often appears in DS_METODOLOGIA)
    funding_source_mentioned: bool = Field(
        description="True if the funding source / contratante is mentioned in the methodology text."
    )
    funding_source_text: str = Field(
        default="",
        description="Brief quote if funding is mentioned. Empty otherwise.",
    )

    extraction_notes: str = Field(
        default="",
        description="Free-form notes on ambiguity or judgment calls.",
    )


# ─── poll_bairro_detail ──────────────────────────────────────────────
#
# Per-poll bairro/município PDF — the "complement" that DS_DADO_MUNICIPIO
# defers to when pollsters use Res 23.600/2019 §7°. Available for ~13,200
# of the 14,876 mayor polls in the registry (94.4% of deferred polls
# have one). Resolves coverage_class for the 36.9% of polls otherwise
# stuck at deferred_complement.
#
# Source format varies widely by pollster: tabular IBGE-setor-coded
# (QUAEST-style), tabular bairros × n_entrevistas (most), regional
# (REGIÃO/Distrito/Bairros), or narrative ("Bairro X: N entrevistas").
# A small but non-trivial subset (~12% sampled) shows only "PESQUISA
# NÃO REALIZADA" — flagged via its own enum value.

# NOTE: CoverageClassResolved enum removed in v2. Coverage class + rural are no
# longer inferred from bairro NAME STRINGS in the extractor (subjective, hard to
# audit). They are derived downstream from matched IBGE setor situacao (urbano/
# rural) + an electorate-coverage ratio — see docs/decisions.md. If a rural guess
# is ever wanted for name-only PDFs, that is a separate optional downstream LLM
# pass, deliberately NOT baked into this faithful extraction.


class CoverageUnit(BaseModel):
    """One geographic allocation unit (a row) as printed in the PDF.

    Carries whatever identifiers the PDF gives that row — any of a bairro
    name, an IBGE setor code, a distrito — plus its interview count. One
    unified row grain across all PDF formats: name-tabular PDFs fill
    `bairro_name`; QUAEST/setor PDFs fill `setor_code`; some fill both.
    Downstream matches on whichever identifier is present.
    """
    bairro_name: Optional[str] = Field(
        default=None,
        description=(
            "Bairro / localidade name, verbatim, if the row names one. "
            "Null for setor-only rows (e.g. per-interview setor microdata)."
        ),
    )
    setor_code: Optional[str] = Field(
        default=None,
        description=(
            "IBGE setor censitário code (12-15 digit numeric string) for "
            "this row, verbatim, if printed. Null when the row has no setor "
            "code. Capture it whenever present — it keys deterministic "
            "urban/rural downstream."
        ),
    )
    distrito: Optional[str] = Field(
        default=None,
        description=(
            "Distrito / região this row belongs to, if the PDF groups by "
            "distrito (e.g. RJ-style REGIÃO/Distrito). Null otherwise."
        ),
    )
    n_entrevistas: Optional[int] = Field(
        default=None,
        description=(
            "Interviews allocated to this unit, if stated. Null when not "
            "reported. For regional layouts with a 'Total Região' line, "
            "report the per-unit count, not the region total."
        ),
    )


class PollBairroDetail(ExtractionSchema):
    """Raw geographic allocation list from the per-poll bairro/município PDF.

    v4: ONE faithful list of the rows as the PDF prints them (`units`), each
    carrying whatever identifiers appear — bairro name, IBGE setor code,
    distrito, interview count. No more / no less than the raw. The LLM does
    NOT count or sum: v3's n_units_total and total_interviews_distributed are
    dropped (asking the model for exact aggregates is unreliable and they are
    derivable downstream — len(units), sum of n_entrevistas). The only
    non-row signal is a reliable `units_truncated` boolean. Coverage class /
    rural / regional-structure / distrito lists are NOT stored — all derivable
    downstream (matched IBGE setor situacao + electorate ratio; set of unit
    distritos). See docs/decisions.md.
    """
    schema_name: ClassVar[str] = "poll_bairro_detail"
    schema_version: ClassVar[str] = "v5"

    pesquisa_realized: bool = Field(
        description=(
            "True normally. False ONLY when the PDF is the "
            "'PESQUISA NÃO REALIZADA' stamp (poll was cancelled). "
            "When false, all other fields default to empty."
        )
    )

    units: list[CoverageUnit] = Field(
        default_factory=list,
        description=(
            "Every DISTINCT geographic allocation unit the PDF lists, in "
            "printed order, each with the identifiers that row carries "
            "(bairro_name / setor_code / distrito / n_entrevistas). Dedup to the "
            "finest printed unit: for per-interview setor microdata, emit "
            "one unit per distinct setor with its interview count (NOT one "
            "row per interview). HARD CAP 80 units (token budget); if the "
            "PDF has more, keep the 80 with the largest n_entrevistas and "
            "set units_truncated=true. Empty only for a not-realized stamp."
        ),
    )
    units_truncated: bool = Field(
        default=False,
        description=(
            "True ONLY if the PDF lists MORE distinct units than the ones "
            "returned (i.e. the 80-unit cap was hit and some were omitted). "
            "False normally. This is a yes/no observation, not a count — do "
            "not try to total the units; downstream counts len(units)."
        ),
    )

    extraction_notes: str = Field(
        default="",
        description=(
            "Free-form notes on ambiguity, format unusual, or PDF "
            "truncation. Flag here if the PDF is text-thin (likely an "
            "image-only scan that needs OCR)."
        ),
    )


# ─────────────────────────────────────────────────────────────────────
# poll_questionario — survey questionnaire PDF extraction
# (PesqEle filing: `questionario_pesquisa` PDF). Captures the survey
# instrument: question wording, candidate roster ordering across
# `estimulada`/`espontânea` scenarios, name rotation, and any
# nonresponse-handling notes that the registration narrative omits.
# ─────────────────────────────────────────────────────────────────────


class QuestionType(str, Enum):
    estimulada = "estimulada"          # candidate names shown to respondent
    espontanea = "espontanea"          # spontaneous, no names shown
    avaliacao = "avaliacao"            # approval/evaluation (Bom/Ruim, Ótimo/Péssimo)
    rejeicao = "rejeicao"              # explicit "never vote for" question
    party = "party"                    # party-preference question (which party, not candidate)
    demographic = "demographic"         # sex/age/education/income/race
    issue = "issue"                    # issue / agenda question
    screener = "screener"              # eligibility / quota screener
    other = "other"
    unclear = "unclear"


class CandidateOrder(str, Enum):
    alphabetical = "alphabetical"
    by_number = "by_number"            # by número de urna
    by_party = "by_party"
    by_listed = "by_listed"            # the printed order in the questionnaire (no stated rule)
    rotated = "rotated"                # instruction to rotate / alternate name order across respondents
    random = "random"                  # explicit randomization instruction
    unclear = "unclear"
    not_applicable = "not_applicable"  # no candidate roster in this question


class QuestionnaireScenario(BaseModel):
    """One question block from the questionnaire PDF, in filing order.

    This models EVERY block in the instrument — not only vote-intention
    scenarios but also approval/rejection, party-preference, issue,
    screener and demographic blocks — so the downstream analysis can
    reconstruct question ordering and priming structure (e.g. an approval
    or rejection item placed BEFORE the first estimulada). The order and
    `position` of blocks is load-bearing; never reorder them.
    """

    position: int = Field(
        description=(
            "1-based filing order of this block in the instrument "
            "(1 = first question printed). MUST reflect the true printed "
            "order; this is what lets the analysis test whether an "
            "approval/rejection item precedes the first estimulada."
        )
    )
    label: str = Field(
        description=(
            "The exact label or number used in the PDF, verbatim. "
            "E.g. 'P5', 'ESTIMULADA 1', 'ESPONTÂNEA', 'CENÁRIO A — "
            "COM CANDIDATO X'. If unlabeled, use 'unlabeled_<N>'."
        )
    )
    question_type: QuestionType = Field(
        description="Classification per the QuestionType enum."
    )
    question_text: str = Field(
        default="",
        description=(
            "1-2 sentences of the question prompt as written, verbatim "
            "Portuguese. Up to ~300 chars. If the question is mainly "
            "a candidate list with a stem like 'Se a eleição fosse "
            "hoje, em quem o(a) Sr.(a) votaria?', include the stem here."
        ),
    )
    candidates_listed: list[str] = Field(
        default_factory=list,
        description=(
            "VOTE-INTENTION ROSTER ONLY: candidate / option names as "
            "listed in the PDF, in the order they appear. Up to 15 "
            "entries. Preserve original capitalization. Populate for "
            "`estimulada` scenarios (the closed list shown to the "
            "respondent). Leave empty for every other question_type — "
            "use `subject_candidates` to record who an approval / "
            "rejection / issue question is ABOUT."
        ),
    )
    subject_candidates: list[str] = Field(
        default_factory=list,
        description=(
            "WHO THIS QUESTION IS ABOUT, when it targets specific "
            "candidate(s) but is NOT a vote-intention roster. Populate "
            "for `avaliacao` (the candidate(s) being rated), `rejeicao` "
            "(the candidate(s) named in a 'nunca votaria em X' item, if "
            "named rather than open), and `issue` items that name a "
            "candidate. Verbatim names, preserve capitalization. Empty "
            "for estimulada/espontanea (use candidates_listed), party, "
            "demographic and screener blocks. This is the primitive that "
            "lets the analysis match the item against the sponsor / the "
            "sponsor's opponent — do NOT judge sponsorship here, just "
            "record the names the PDF states."
        ),
    )
    candidate_order: CandidateOrder = Field(
        description=(
            "How the candidate list is ordered. 'rotated' or "
            "'random' only when the PDF explicitly instructs the "
            "interviewer to rotate / randomize. 'by_listed' for any "
            "printed order with no stated rule. 'not_applicable' for "
            "non-vote-intention questions."
        )
    )


class PollQuestionario(ExtractionSchema):
    """Survey-instrument extraction from `questionario_pesquisa` PDF.

    The core output is `scenarios`: the COMPLETE, ORDERED transcript of
    every question block in the instrument (vote-intention, approval,
    rejection, party, issue, screener, demographic), in true filing
    order. Presence flags, counts, and priming diagnostics are NOT
    extracted as separate judgments — they are derived downstream from
    this ordered transcript crossed with sponsor identity. In
    particular, Fernando's priming hypothesis (an approval item about
    the sponsor's candidate, or a rejection item about an opponent,
    placed BEFORE the first estimulada) is a predicate over
    `position` + `question_type` + `subject_candidates`, computed in the
    Panel-B analysis — not here.
    """

    schema_name: ClassVar[str] = "poll_questionario"
    schema_version: ClassVar[str] = "v3"

    pesquisa_realized: bool = Field(
        description=(
            "True normally. False ONLY when the PDF is a "
            "'PESQUISA NÃO REALIZADA' stamp. When false, all other "
            "fields default to empty / unclear."
        )
    )

    scenarios: list[QuestionnaireScenario] = Field(
        default_factory=list,
        description=(
            "The COMPLETE instrument transcript: EVERY question block, "
            "in true printed (filing) order, each with its 1-based "
            "`position`. Include vote-intention (estimulada/espontanea), "
            "approval (avaliacao), rejection (rejeicao), party, issue, "
            "screener AND demographic blocks — do NOT drop or reorder "
            "any. NEVER reorder to group by type: the order is the "
            "signal. Verbosity is tiered to stay within budget: for "
            "estimulada/avaliacao/rejeicao/party blocks give full "
            "question_text + candidates_listed / subject_candidates; for "
            "demographic/screener/issue blocks a one-line question_text "
            "(or just the label) is enough — but still list them in "
            "position order. HARD CAP 30 blocks: if the instrument is "
            "longer, keep the first 30 IN ORDER (never skip ahead) and "
            "set scenarios_truncated=true. Do NOT count or total the "
            "scenarios — downstream derives counts/positions from this list."
        ),
    )
    scenarios_truncated: bool = Field(
        default=False,
        description=(
            "True ONLY if the instrument has MORE question blocks than "
            "the (cap-30) ones returned. False normally. A yes/no "
            "observation, not a count — downstream derives the "
            "vote-intention count, first-estimulada position and headline "
            "label from the scenarios transcript (count of "
            "estimulada+espontanea; min position where type==estimulada; "
            "its label)."
        ),
    )

    name_rotation_documented: bool = Field(
        default=False,
        description=(
            "True if the PDF anywhere documents an instruction to "
            "rotate / alternate / randomize candidate name order "
            "across respondents (e.g. 'inverter ordem dos nomes', "
            "'rotacionar', 'alternar a cada entrevista'). False for "
            "fixed-order printed rosters."
        ),
    )
    name_rotation_evidence: str = Field(
        default="",
        description=(
            "Verbatim quote or close paraphrase, 1-2 sentences, of "
            "the rotation instruction. Empty when name_rotation_"
            "documented is False."
        ),
    )

    nonresponse_instruction_present: bool = Field(
        default=False,
        description=(
            "True if the questionnaire contains any printed "
            "instruction about handling undecided / refusal / "
            "blank / null responses (e.g. 'NÃO LER ESTAS OPÇÕES', "
            "'redistribuir indecisos proporcionalmente', "
            "'descartar brancos'). False otherwise."
        ),
    )
    nonresponse_instruction_text: str = Field(
        default="",
        description=(
            "Verbatim or paraphrased text of the nonresponse "
            "instruction, up to ~400 chars Portuguese. Empty when "
            "nonresponse_instruction_present is False."
        ),
    )

    # NOTE: approval_question_present, rejection_question_present and
    # asks_party_first were removed in v2. They are now DERIVED from the
    # ordered `scenarios` transcript (presence = any block of that type;
    # asks_party_first = position(party) < first_estimulada_position),
    # which also recovers directionality + ordering the booleans discarded.

    extraction_notes: str = Field(
        default="",
        description=(
            "Free-form notes on PDF format anomalies, OCR concerns, "
            "or schema fits poorly (e.g. instrument is a different "
            "language, the PDF is a relatório attached by mistake). "
            "Empty when the extraction is clean."
        ),
    )


# ── poll_weighting: post-fielding ponderação / correction ─────────────

class WeightingApplication(str, Enum):
    always_applied = "always_applied"
    conditional = "conditional"               # only if sample deviates from quotas
    described_unclear_application = "described_unclear_application"
    not_described = "not_described"


class WeightingTarget(str, Enum):
    tse_eleitorado = "tse_eleitorado"
    ibge_census_2022 = "ibge_census_2022"
    ibge_census_2010 = "ibge_census_2010"
    muni_population_unspecified = "muni_population_unspecified"
    historical_turnout = "historical_turnout"
    mixed = "mixed"
    other = "other"
    not_specified = "not_specified"


class PollWeighting(ExtractionSchema):
    """Post-fielding weighting / ponderação description.

    Reads: DS_METODOLOGIA_PESQUISA + DS_PLANO_AMOSTRAL + DS_SISTEMA_CONTROLE.

    Complements PollSampling (which captures the quota DESIGN). This task
    captures the *post-fielding correction* that may or may not normalize
    sample shares back to population shares. The distinction matters for
    Channel A: quotas without weighting → directly biased; quotas with
    weighting back to population → not biased.
    """
    schema_name: ClassVar[str] = "poll_weighting"
    schema_version: ClassVar[str] = "v2"

    # NOTE: `described` removed in v2 — derive it as (application !=
    # not_described). `application` already carries the presence signal.
    application: WeightingApplication = Field(
        description=(
            "How the weighting is applied. always_applied: text says weights "
            "are always applied. conditional: text says weights are applied "
            "ONLY if sample deviates from quotas by some threshold (very common "
            "Brazilian pattern: 'caso ocorram diferenças superiores à margem "
            "de erro'). described_unclear_application: weighting mentioned but "
            "application conditions ambiguous. not_described: no weighting "
            "described at all."
        )
    )
    variables_weighted: list[str] = Field(
        default_factory=list,
        description=(
            "Variables EFFECTIVELY re-weighted. Use lowercase short tokens: "
            "sex, age, education, income, region, race. EXCLUDE any variable "
            "the text explicitly leaves unweighted (fator = 1, 'resultados "
            "obtidos no campo', 'sem ponderação para X') — merely naming a "
            "variable in the weighting sentence is NOT enough. Empty list if "
            "not described."
        )
    )
    variables_explicitly_unweighted: list[str] = Field(
        default_factory=list,
        description=(
            "Variables the text EXPLICITLY declares left unweighted "
            "(fator de ponderação = 1, 'resultados obtidos no campo', 'sem "
            "ponderação'). Lowercase tokens (sex, age, education, income, "
            "region, race). Empty if none. This is the mechanism-honest "
            "lever: a variable here is deliberately NOT corrected, which is "
            "distinct from a variable simply not mentioned — downstream the "
            "income lever is live wherever income is unweighted."
        ),
    )
    target: WeightingTarget = Field(
        description=(
            "Population reference the weights claim to normalize toward. "
            "tse_eleitorado: TSE eligible-voter file (SIG eleitorado). "
            "ibge_census_2022 / ibge_census_2010: explicitly named IBGE censo. "
            "muni_population_unspecified: 'a população do município' without "
            "naming source. historical_turnout: weighted by past-turnout share. "
            "not_specified: no target stated."
        )
    )
    target_evidence: str = Field(
        default="",
        description="Short verbatim quote describing the weighting target. Empty if not described."
    )
    post_stratification_explicit: bool = Field(
        description=(
            "True if the text EXPLICITLY states the weights normalize sample "
            "shares back to population/target shares (e.g., 'ponderação para "
            "corrigir desvios entre amostra obtida e amostra planejada', "
            "'pesos calibrados pela distribuição populacional'). False if "
            "weighting is mentioned but the corrective intent is not explicit."
        )
    )
    conditional_threshold_pp: Optional[float] = Field(
        default=None,
        description=(
            "If application is 'conditional' and a numeric threshold is stated "
            "(e.g., 'caso difira mais de 5 pp da amostra planejada'), the "
            "threshold in percentage points. Null otherwise."
        )
    )
    correction_method: str = Field(
        default="",
        description=(
            "Short label for the correction method if named: 'raking', "
            "'post-stratification', 'IPW', 'calibração', 'ponderação simples', "
            "etc. Empty if not named."
        )
    )

    text_truncated: bool = Field(default=False)
    extraction_notes: str = Field(default="")
