"""Pydantic schema for the registered-slate estimulado extraction.

INTENT. Redesign of the vote-share extraction (docs/todo.md § Extraction
pipeline; spec at projects/poll-sponsor-bias/docs/notes/
extraction-registered-slate-redesign.md). For polls registered AFTER the
candidacy-registration deadline the municipal slate is final, so instead
of extracting every printed scenario and fuzzy-matching names to the TSE
registry, we pass the official registered slate into the prompt and ask
the model for the ONE estimulado scenario whose candidate set matches the
slate — keyed on número de urna, which pollsters cannot restyle the way
they restyle nomes de urna.

REASONING. This lives in a NEW module (not schemas.py) to keep the
existing PollRelatorio task and its ~10k-entry cache untouched — the
redesign is additive, running alongside the current extractor rather than
replacing it. See poll_relatorio_registered.py for the extractor wrapper
and extract_registered.py for the driver.

ASSUMES. numero_cand echoes the ballot numbers supplied in the prompt
slate (NUMERO_CAND from build/clean/candidato.csv); the driver validates
the returned set against the slate in code — the model is not trusted to
enforce the exact-match acceptance criterion on its own.
"""
from __future__ import annotations

from typing import ClassVar, Optional

from pydantic import BaseModel, Field

from llmkit import ExtractionSchema


class RegisteredEstimate(BaseModel):
    numero_cand: str = Field(
        description=(
            "Ballot number (número de urna), echoed EXACTLY from the "
            "registered-slate list supplied in the prompt. This is the "
            "join key — do not invent numbers not in the slate. Return one "
            "entry for EVERY candidate in the slate."
        )
    )
    nome_urna: str = Field(
        description=(
            "Candidate ballot name as printed in the chosen scenario. If "
            "the ticket is printed as 'Prefeito e Vice', give the prefeito "
            "(lead) name only."
        )
    )
    percent: Optional[float] = Field(
        default=None,
        description=(
            "Stimulated vote-intention percentage (0-100) for this "
            "candidate in the chosen estimulado scenario. Null ONLY if the "
            "candidate is in the registered slate but genuinely does not "
            "appear in that scenario — do not guess a number."
        ),
    )


class PollRelatorioRegistered(ExtractionSchema):
    """Estimulado shares filled in against the TSE registered slate.

    The model is given the município's registered slate and asked to (a)
    identify the estimulado scenario for the mayoral race and (b) fill in
    each registered candidate's vote share in it (número echoed → the
    driver maps to politico_id EXACTLY, no fuzzy name match). extra_
    candidates flags any non-slate names found in the scenario — a
    quality signal (slate gap or the model force-fitting the wrong table).
    """
    schema_name: ClassVar[str] = "poll_relatorio_registered"
    schema_version: ClassVar[str] = "v2"

    tse_protocol: str = Field(
        description=(
            "TSE registration number, format 'XX-NNNNN/YYYY'. Echo from "
            "the PDF for join-back validation."
        )
    )
    scenario_found: bool = Field(
        description=(
            "True if an 'intenção de voto estimulada' scenario for the "
            "PREFEITO race was found in the document. False when the PDF "
            "has no stimulated mayoral vote-intention scenario at all "
            "(e.g. it is a sampling-plan attachment, or only espontânea "
            "is present)."
        )
    )
    scenario_label: str = Field(
        default="",
        description=(
            "The exact label of the chosen estimulado scenario as printed "
            "in the PDF (e.g. 'Prefeito - Estimulada'). Empty when "
            "scenario_found is False."
        ),
    )
    estimates: list[RegisteredEstimate] = Field(
        default_factory=list,
        description=(
            "One entry per candidate in the SUPPLIED SLATE (fill them all "
            "in; use percent=null for any slate candidate absent from the "
            "scenario). Empty only when scenario_found is False."
        ),
    )
    extra_candidates: list[str] = Field(
        default_factory=list,
        description=(
            "Names appearing in the chosen estimulado scenario that are "
            "NOT in the registered slate, excluding aggregate rows "
            "(Branco/Nulo, Não sabe) and vice-prefeito running mates. "
            "Normally empty; a non-empty list means either the slate is "
            "incomplete or the wrong scenario/table was selected — a "
            "quality flag for the driver, not an error."
        ),
    )
    extraction_notes: str = Field(
        default="",
        description=(
            "Brief note on any ambiguity — multiple estimulado scenarios, "
            "spelling reconciliation, or a slate/PDF discrepancy."
        ),
    )
