"""poll_sampling extractor — sampling design, sample size, quotas,
population reference. One of the three poll-methodology tasks.

Reads: DS_METODOLOGIA_PESQUISA + DS_PLANO_AMOSTRAL.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from llmkit import LLMCache, extract
from llmkit.cache import content_hash
from llmkit.extract import ExtractionResult

from schemas import PollSampling

load_dotenv()

BASE_DIR = Path(os.environ["BASE_DIR"])
HERE = Path(__file__).resolve().parent
PROMPT_DIR = HERE / "prompts"

MODEL = "gpt-4o-mini"
MIN_TEXT_CHARS = 200
MAX_TEXT_CHARS = 30_000

CANONICAL_CACHE_DIR = BASE_DIR / "build" / "llm" / "poll_sampling"
CACHE = LLMCache(CANONICAL_CACHE_DIR)


def _load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


SYSTEM_PROMPT = _load_prompt("poll_sampling_system.txt")
USER_TEMPLATE = _load_prompt("poll_sampling_user.txt")
SYSTEM_PROMPT_HASH = content_hash(SYSTEM_PROMPT)


def truncate(text: str, max_chars: int = MAX_TEXT_CHARS) -> str:
    return text[:max_chars] if len(text) > max_chars else text


def extract_poll_sampling(
    *,
    protocol: str,
    ds_metodologia: str,
    ds_plano_amostral: str,
    uf: str,
    institute: str,
    client,
    model: str = MODEL,
    cache: LLMCache | None = None,
    reextract: bool = False,
) -> Optional[ExtractionResult]:
    """Returns None when the combined input is too thin to extract."""
    c = CACHE if cache is None else cache
    ds_metodologia = truncate(str(ds_metodologia or ""))
    ds_plano_amostral = truncate(str(ds_plano_amostral or ""))
    combined = ds_metodologia + "\n\n" + ds_plano_amostral
    if len(combined.strip()) < MIN_TEXT_CHARS:
        return None

    user_prompt = USER_TEMPLATE.format(
        protocol=protocol,
        uf=uf,
        institute=institute or "",
        ds_metodologia=ds_metodologia,
        ds_plano_amostral=ds_plano_amostral,
    )
    return extract(
        doc_id=str(protocol),
        text=combined,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=PollSampling,
        model=model,
        cache=c,
        client=client,
        reextract=reextract,
        use_structured_outputs=True,
        schema_in_cache_key=True,
    )
