"""poll_questionario extractor — per-poll survey instrument PDF.

Reads the per-protocol PDF from questionario_pesquisa_2024.zip and
extracts the survey instrument: question wording, candidate roster
ordering across estimulada / espontanea scenarios, name rotation, and
any nonresponse instructions printed inside the questionnaire.

Targets the levers the registration narrative cannot reach:
within-poll scenario selection, name-order priming, candidate-roster
composition.

Input source: zip at
  pipelines/politica/build/scrape/tse_polls_2024/questionario_pesquisa_2024.zip
Filename convention: {NR_PROTOCOLO_REGISTRO}_{TSE_DOC_ID}_questionario_pesquisa.pdf
(e.g. SP014112024_423571_questionario_pesquisa.pdf)
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from llmkit import LLMCache, extract
from llmkit.cache import content_hash
from llmkit.extract import ExtractionResult

from schemas import PollQuestionario

load_dotenv()

BASE_DIR = Path(os.environ["BASE_DIR"])
HERE = Path(__file__).resolve().parent
PROMPT_DIR = HERE / "prompts"

MODEL = "gpt-4o-mini"
MIN_TEXT_CHARS = 20         # "PESQUISA NÃO REALIZADA" is ~27 chars; lower bound
MAX_TEXT_CHARS = 60_000     # questionnaires can be long — cap ~15k tokens

CANONICAL_CACHE_DIR = BASE_DIR / "build" / "llm" / "poll_questionario"
CACHE = LLMCache(CANONICAL_CACHE_DIR)


def _load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


SYSTEM_PROMPT = _load_prompt("poll_questionario_system.txt")
USER_TEMPLATE = _load_prompt("poll_questionario_user.txt")
SYSTEM_PROMPT_HASH = content_hash(SYSTEM_PROMPT)


def pdf_to_text(pdf_bytes: bytes) -> str:
    """Decode a PDF passed as bytes via pdftotext -layout."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        tmp_path = f.name
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", tmp_path, "-"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout
    finally:
        os.unlink(tmp_path)


def truncate(text: str, max_chars: int = MAX_TEXT_CHARS) -> str:
    return text[:max_chars] if len(text) > max_chars else text


def extract_poll_questionario(
    *,
    protocol: str,
    pdf_bytes: bytes,
    municipality: str,
    uf: str,
    institute: str,
    client,
    model: str = MODEL,
    cache: LLMCache | None = None,
    reextract: bool = False,
) -> Optional[ExtractionResult]:
    """Extract survey-instrument features from one questionnaire PDF.

    Returns None when the PDF is image-only (no text recovered).
    "PESQUISA NÃO REALIZADA" stamps DO go to the LLM so we get a clean
    not_realized classification — the schema has its own bucket.
    """
    c = CACHE if cache is None else cache
    text = pdf_to_text(pdf_bytes)
    if len(text.strip()) < MIN_TEXT_CHARS:
        return None
    text = truncate(text)
    user_prompt = USER_TEMPLATE.format(
        protocol=protocol,
        municipality=municipality or "",
        uf=uf,
        institute=institute or "",
        pdf_text=text,
    )
    return extract(
        doc_id=str(protocol),
        text=text,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=PollQuestionario,
        model=model,
        cache=c,
        client=client,
        reextract=reextract,
        use_structured_outputs=True,
        schema_in_cache_key=True,
        # 16k matches the bairro extractor — handles the long-tail
        # questionnaires with 5+ scenarios and large rosters.
        max_tokens=16_000,
    )
