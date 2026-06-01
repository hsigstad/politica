"""Pydantic schemas for politica LLM extractions.

Currently one task: poll relatório extraction (per-candidate vote intentions
from TSE-registered poll relatório PDFs).
"""
from __future__ import annotations

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
