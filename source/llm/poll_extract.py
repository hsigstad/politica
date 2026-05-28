"""Extract per-candidate vote intentions from TSE relatório PDFs.

Moved into pipelines/politica 2026-05-28 from
projects/REDACTED-PROJECT/source/llm/ so the LLM-extracted poll table
can be workspace-wide infrastructure rather than legacy-pilot-private.

Reads PDFs from build/scrape/tse_relatorio/{year}/{PROTOCOLO}.pdf, runs each
through pdftotext + an LLM with structured JSON output, validates against a
Pydantic schema, and caches one JSON per protocol at
build/llm/poll_relatorio/{PROTOCOLO}.json. After processing, writes a combined
build/llm/poll_relatorio.parquet long-format (one row per candidate-scenario).

Schema is intentionally narrow: we only ask the LLM for what's NEW in the PDF
(per-candidate vote intentions per scenario), since institute, dates, sample
size, municipality, methodology are all already in pesquisa_eleitoral_{year}.csv
and join by protocol.

Image-only PDFs (where pdftotext returns near-zero chars) are skipped with a
"text_unreadable" cache entry. An OCR fallback is left for a future pass.

Usage:
    python source/llm/poll_extract.py --year 2024
    python source/llm/poll_extract.py --year 2024 --limit 50 --model gpt-4o-mini
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import pandas as pd
from openai import OpenAI
from pydantic import BaseModel, Field

import path

MIN_TEXT_CHARS = 200  # below this we treat the PDF as image-only


# ---------- Schema (simplified per the pilot finding) ----------

class CandidateResult(BaseModel):
    candidate_name: str = Field(description="Candidate display name. For aggregate rows like 'Branco/Nulo' or 'Não sabe', use a descriptive label.")
    party: Optional[str] = Field(default=None, description="Party abbreviation if shown next to the name (e.g., 'PL', 'PT'). null if absent or aggregate row.")
    percent: float = Field(description="Vote intention percentage in this scenario, 0-100.")


class Scenario(BaseModel):
    scenario_type: str = Field(description="One of: 'espontaneo', 'estimulado', 'votos_validos', 'rejeicao', 'avaliacao_governo', 'segundo_turno_simulacao', 'outro'.")
    scenario_label: str = Field(description="The exact label used in the PDF.")
    candidates: list[CandidateResult]


class PollRelatorio(BaseModel):
    tse_protocol: str = Field(description="TSE registration number, format 'XX-NNNNN/YYYY'. Echo from the PDF for join-back validation.")
    scenarios: list[Scenario] = Field(description="All voting-intention scenarios for THIS poll (do not include historical comparison values from previous waves).")
    extraction_notes: str = Field(default="", description="Brief note about any ambiguity or judgment call.")


SYSTEM_PROMPT = """You extract per-candidate vote intentions from Brazilian TSE relatório PDFs (text extracted by pdftotext).

Each PDF reports ONE registered poll. The PDF may reference earlier waves — extract ONLY the current/latest poll's results, not the historical comparison values.

Conventions:
- "Estimulado" = stimulated (names read). "Espontâneo" = spontaneous (open-ended).
- "Votos válidos" = valid votes (excludes Brancos/Nulos/Indecisos).
- Some institutes report rejection ("rejeição"), government evaluation ("avaliação"), and second-round simulations alongside vote intention — include them as separate scenarios.
- For aggregate rows like "Branco/Nulo", "Não sabe", emit a CandidateResult with party=null and a descriptive candidate_name.
- TSE registration number is on every PDF, format "XX-NNNNN/YYYY".
- We DO NOT need methodology, dates, sample size, institute, contracting party — those join from a separate CSV. Focus on the vote intention numbers.

If the text is too garbled to extract anything, return an empty scenarios list and explain in extraction_notes.
"""


def pdf_to_text(pdf_path: Path) -> str:
    out = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout


def cli_to_display(protocol: str) -> str:
    """AC094012020 → AC-09401/2020."""
    return f"{protocol[:2]}-{protocol[2:7]}/{protocol[7:]}"


def extract_one(client: OpenAI, pdf_path: Path, model: str) -> dict:
    """Run pdftotext + LLM extraction. Returns dict with status + extraction or error."""
    text = pdf_to_text(pdf_path)
    if len(text) < MIN_TEXT_CHARS:
        return {
            "status": "text_unreadable",
            "pdf_chars": len(text),
            "model": model,
        }
    text_sent = text[:120_000]  # safety cap (~30k tokens)
    protocol = pdf_path.stem
    user_prompt = (
        f"TSE protocol: {cli_to_display(protocol)}\n\n"
        f"PDF text (pdftotext -layout):\n---\n{text_sent}\n---\n\n"
        "Extract vote intentions for the CURRENT poll only."
    )
    t0 = time.monotonic()
    resp = client.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format=PollRelatorio,
        temperature=0,
    )
    parsed = resp.choices[0].message.parsed
    if parsed is None:
        return {
            "status": "model_refused",
            "model": model,
            "raw": resp.choices[0].message.content,
        }
    return {
        "status": "ok",
        "model": model,
        "pdf_chars": len(text),
        "pdf_chars_sent": len(text_sent),
        "extract_seconds": round(time.monotonic() - t0, 2),
        "usage": {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
        },
        "extraction": parsed.model_dump(),
    }


def assemble_parquet(cache_dir: Path, out_path: Path) -> None:
    """Combine all cached JSONs into a long-format parquet (one row per candidate-scenario)."""
    rows = []
    for j in sorted(cache_dir.glob("*.json")):
        d = json.loads(j.read_text(encoding="utf-8"))
        if d.get("status") != "ok":
            continue
        protocol = j.stem
        for s in d["extraction"]["scenarios"]:
            for c in s["candidates"]:
                rows.append({
                    "protocol": protocol,
                    "tse_protocol_display": d["extraction"]["tse_protocol"],
                    "scenario_type": s["scenario_type"],
                    "scenario_label": s["scenario_label"],
                    "candidate_name": c["candidate_name"],
                    "party": c.get("party"),
                    "percent": c["percent"],
                    "extraction_notes": d["extraction"].get("extraction_notes", ""),
                })
    if not rows:
        print("No successful extractions to assemble.")
        return
    df = pd.DataFrame(rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    print(f"\nAssembled {len(df):,} candidate-scenario rows from {df['protocol'].nunique()} polls → {out_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, choices=[2020, 2024], required=True)
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--reextract", action="store_true", help="ignore cache and re-extract")
    args = ap.parse_args()

    pdfs_dir = path.build_scrape_dir / "tse_relatorio" / str(args.year)
    cache_dir = path.build_llm_dir / "poll_relatorio"
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_parquet = path.build_llm_dir / f"poll_relatorio_{args.year}.parquet"

    pdfs = sorted(pdfs_dir.glob("*.pdf"))
    if args.limit:
        pdfs = pdfs[: args.limit]
    print(f"PDFs to process: {len(pdfs)}  cache: {cache_dir}  model: {args.model}")
    if not pdfs:
        sys.exit("No PDFs to process. Run source/scrape/tse_relatorio.py first.")

    client = OpenAI()
    counts = {"ok": 0, "cached": 0, "text_unreadable": 0, "error": 0}
    total_in = total_out = 0

    for i, pdf in enumerate(pdfs, 1):
        protocol = pdf.stem
        cache_path = cache_dir / f"{protocol}.json"
        if cache_path.exists() and not args.reextract:
            counts["cached"] += 1
            continue
        try:
            result = extract_one(client, pdf, args.model)
        except Exception as e:
            result = {"status": "error", "error": repr(e), "model": args.model}
        cache_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        if result["status"] == "ok":
            counts["ok"] += 1
            total_in += result["usage"]["prompt_tokens"]
            total_out += result["usage"]["completion_tokens"]
        elif result["status"] == "text_unreadable":
            counts["text_unreadable"] += 1
        else:
            counts["error"] += 1
        if i % 25 == 0 or i == len(pdfs):
            cost = total_in / 1e6 * 0.15 + total_out / 1e6 * 0.60  # gpt-4o-mini pricing
            print(f"  [{i}/{len(pdfs)}] totals: {counts}  tokens: in={total_in:,} out={total_out:,}  cost≈${cost:.3f}")

    print(f"\nDONE. Counts: {counts}")
    cost = total_in / 1e6 * 0.15 + total_out / 1e6 * 0.60
    print(f"Total tokens (this run): in={total_in:,} out={total_out:,}  cost≈${cost:.3f}")

    # Assemble parquet
    assemble_parquet(cache_dir, out_parquet)


if __name__ == "__main__":
    main()
