"""poll_coverage extractor — geographic coverage (the single most
consequential design field for Channel A). One of the three
poll-methodology tasks.

Reads: DS_DADO_MUNICIPIO (primary) + DS_PLANO_AMOSTRAL (context).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from llmkit import LLMCache, extract
from llmkit.cache import content_hash
from llmkit.extract import ExtractionResult

from schemas import PollCoverage

load_dotenv()

BASE_DIR = Path(os.environ["BASE_DIR"])
HERE = Path(__file__).resolve().parent
PROMPT_DIR = HERE / "prompts"

MODEL = "gpt-4o-mini"
# Coverage text can be very short ("Será informado em complemento") —
# accept down to ~50 chars; an empty / NaN field is a separate signal.
MIN_TEXT_CHARS = 30
MAX_TEXT_CHARS = 20_000

CANONICAL_CACHE_DIR = BASE_DIR / "build" / "llm" / "poll_coverage"
CACHE = LLMCache(CANONICAL_CACHE_DIR)


def _load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


SYSTEM_PROMPT = _load_prompt("poll_coverage_system.txt")
USER_TEMPLATE = _load_prompt("poll_coverage_user.txt")
SYSTEM_PROMPT_HASH = content_hash(SYSTEM_PROMPT)


def truncate(text: str, max_chars: int = MAX_TEXT_CHARS) -> str:
    return text[:max_chars] if len(text) > max_chars else text


def extract_poll_coverage(
    *,
    protocol: str,
    ds_dado_municipio: str,
    ds_plano_amostral: str,
    municipality: str,
    uf: str,
    client,
    model: str = MODEL,
    cache: LLMCache | None = None,
    reextract: bool = False,
) -> Optional[ExtractionResult]:
    """Returns None when DS_DADO_MUNICIPIO is empty / whitespace —
    those polls register as a separate signal (coverage field blank)
    handled by the caller, not as an LLM extraction."""
    c = CACHE if cache is None else cache
    ds_dado_municipio = truncate(str(ds_dado_municipio or ""))
    ds_plano_amostral = truncate(str(ds_plano_amostral or ""))
    if len(ds_dado_municipio.strip()) < MIN_TEXT_CHARS:
        return None

    user_prompt = USER_TEMPLATE.format(
        protocol=protocol,
        municipality=municipality or "",
        uf=uf,
        ds_dado_municipio=ds_dado_municipio,
        ds_plano_amostral=ds_plano_amostral,
    )
    # Cache key text = the actual extracted-from content (coverage
    # field), not the context. That way a different município that
    # shares the same DS_DADO_MUNICIPIO boilerplate hits the same
    # cache entry.
    return extract(
        doc_id=str(protocol),
        text=ds_dado_municipio,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=PollCoverage,
        model=model,
        cache=c,
        client=client,
        reextract=reextract,
        use_structured_outputs=True,
        schema_in_cache_key=True,
    )
