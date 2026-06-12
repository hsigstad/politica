"""Batch-API version of extract_methodology.py.

The synchronous version takes ~10s per LLM call (gpt-4o-mini with
Structured Outputs); at 14k polls × 3 tasks that's ~95h. The OpenAI
Batch API processes the same requests for half the price with a 24h
SLA — better fit for the full universe.

This script writes cache files in the exact format the sync wrappers
expect, so after `harvest` you can re-run `extract_methodology.py
--all` and it will find everything cached and just assemble the wide
parquet.

Four phases (one subcommand each):

  build     Construct one JSONL of requests per task, skipping
            protocols already in the cache. For poll_coverage, apply
            the deterministic short-circuit first (deferred /
            very-short / empty go to cache directly without going to
            the LLM).
  submit    Upload each JSONL and create a Batch job. Saves the batch
            IDs to batch_state.json.
  status    Poll each batch and print progress.
  harvest   Download each completed batch's output JSONL, parse the
            responses, and write llmkit-format cache files.

Run:
  PYTHONPATH=/path/to/llmkit:$PWD/source/llm \\
  BASE_DIR=$PWD \\
    python3 extract_methodology_batch.py build --all
    python3 extract_methodology_batch.py submit
    python3 extract_methodology_batch.py status
    python3 extract_methodology_batch.py harvest

Subset:  add --n 200 to `build` for a small smoke test.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Callable

import openai
import pandas as pd
from llmkit import LLMCache
from llmkit.cache import text_hash, content_hash
from openai.lib._parsing import type_to_response_format_param

# Import the existing wrappers' constants so prompts, models, max_chars
# stay in lockstep with the sync path. The wrappers themselves construct
# user prompts identically to what we do below.
import poll_sampling
import poll_coverage
import poll_operations
import poll_bairro_detail
import poll_questionario
from schemas import (
    PollSampling, PollCoverage, PollOperations,
    PollBairroDetail, PollQuestionario,
)

# Same short-circuit logic as the sync orchestrator.
from extract_methodology import (
    coverage_bucket,
    deterministic_coverage_record,
    DEFERRED_PATTERN,
    POLL_COLS,
    RAW_DIR,
    load_universe,
)

BASE_DIR = Path(os.environ["BASE_DIR"])
OUT_DIR = BASE_DIR / "build" / "llm"
OUT_DIR.mkdir(parents=True, exist_ok=True)
BATCH_DIR = OUT_DIR / "batch"
BATCH_DIR.mkdir(parents=True, exist_ok=True)
STATE_PATH = BATCH_DIR / "batch_state.json"

MODEL = "gpt-4o-mini"
TEMPERATURE = 0
MAX_TOKENS = 4000

# ── Task registry ───────────────────────────────────────────────────

class TaskSpec:
    def __init__(self, name, wrapper, schema, *, build_text, build_user_prompt,
                 build_doc_id, max_tokens_override=None):
        self.name = name
        self.wrapper = wrapper           # poll_sampling, poll_coverage, poll_operations,
                                          # poll_bairro_detail, poll_questionario
        self.schema = schema             # Pydantic class
        self.build_text = build_text     # row -> str (the text used for cache hash)
        self.build_user_prompt = build_user_prompt  # row, text -> str
        self.build_doc_id = build_doc_id  # row -> str (protocol)
        self.cache = wrapper.CACHE
        self.system_prompt = wrapper.SYSTEM_PROMPT
        self.user_template = wrapper.USER_TEMPLATE
        self.min_chars = wrapper.MIN_TEXT_CHARS
        self.max_chars = wrapper.MAX_TEXT_CHARS
        self.system_prompt_hash = content_hash(self.system_prompt)
        # Per-task max_tokens override — PollBairroDetail and PollQuestionario
        # need bigger output budgets than the global MAX_TOKENS default.
        self.max_tokens = max_tokens_override or MAX_TOKENS

    def truncate(self, t: str) -> str:
        return t[: self.max_chars] if len(t) > self.max_chars else t


def _truncate(t, max_chars): return t[: max_chars] if len(t) > max_chars else t


def _sampling_text(row, max_chars):
    a = _truncate(str(row.get("DS_METODOLOGIA_PESQUISA") or ""), max_chars)
    b = _truncate(str(row.get("DS_PLANO_AMOSTRAL") or ""), max_chars)
    return a + "\n\n" + b


def _sampling_user_prompt(row, _text, template):
    a = _truncate(str(row.get("DS_METODOLOGIA_PESQUISA") or ""), poll_sampling.MAX_TEXT_CHARS)
    b = _truncate(str(row.get("DS_PLANO_AMOSTRAL") or ""), poll_sampling.MAX_TEXT_CHARS)
    return template.format(
        protocol=str(row["NR_PROTOCOLO_REGISTRO"]),
        uf=str(row["SG_UF"]),
        institute=str(row.get("NM_EMPRESA") or ""),
        ds_metodologia=a,
        ds_plano_amostral=b,
    )


def _coverage_text(row, max_chars):
    return _truncate(str(row.get("DS_DADO_MUNICIPIO") or ""), max_chars)


def _coverage_user_prompt(row, _text, template):
    a = _truncate(str(row.get("DS_DADO_MUNICIPIO") or ""), poll_coverage.MAX_TEXT_CHARS)
    b = _truncate(str(row.get("DS_PLANO_AMOSTRAL") or ""), poll_coverage.MAX_TEXT_CHARS)
    return template.format(
        protocol=str(row["NR_PROTOCOLO_REGISTRO"]),
        municipality=str(row.get("NM_UE") or ""),
        uf=str(row["SG_UF"]),
        ds_dado_municipio=a,
        ds_plano_amostral=b,
    )


def _operations_text(row, max_chars):
    a = _truncate(str(row.get("DS_METODOLOGIA_PESQUISA") or ""), max_chars)
    b = _truncate(str(row.get("DS_SISTEMA_CONTROLE") or ""), max_chars)
    return a + "\n\n" + b


def _operations_user_prompt(row, _text, template):
    a = _truncate(str(row.get("DS_METODOLOGIA_PESQUISA") or ""), poll_operations.MAX_TEXT_CHARS)
    b = _truncate(str(row.get("DS_SISTEMA_CONTROLE") or ""), poll_operations.MAX_TEXT_CHARS)
    return template.format(
        protocol=str(row["NR_PROTOCOLO_REGISTRO"]),
        uf=str(row["SG_UF"]),
        institute=str(row.get("NM_EMPRESA") or ""),
        ds_metodologia=a,
        ds_sistema_controle=b,
    )


def _protocol(row): return str(row["NR_PROTOCOLO_REGISTRO"])


# ── Zip-PDF tasks (bairro_detail, questionario) ─────────────────────
# These two tasks read their input from per-protocol PDFs inside
# pipelines/politica/build/scrape/tse_polls_2024/{bairro_municipio,
# questionario_pesquisa}_2024.zip — a different input shape than the
# registration-CSV-text tasks above. The zip is opened lazily on first
# use and indexed by protocol prefix of the entry name.

import subprocess
import tempfile
import zipfile

_SCRAPE_DIR = BASE_DIR / "build" / "scrape" / "tse_polls_2024"
_ZIP_CACHE: dict[str, tuple[zipfile.ZipFile, dict[str, str]]] = {}


def _open_zip(zipname: str) -> tuple[zipfile.ZipFile, dict[str, str]]:
    """Return (zip handle, {protocol → entry name}). Lazy + cached."""
    if zipname not in _ZIP_CACHE:
        path = _SCRAPE_DIR / zipname
        z = zipfile.ZipFile(path)
        idx = {n.split("_")[0]: n for n in z.namelist()}
        _ZIP_CACHE[zipname] = (z, idx)
    return _ZIP_CACHE[zipname]


def _pdf_to_text(z: zipfile.ZipFile, entry: str, max_chars: int) -> str:
    """Read entry from zip, pdftotext-decode, truncate to max_chars.

    Returns '' on any pdftotext failure (corrupt PDF, image-only, etc.)
    so the build loop's min_chars check naturally skips the protocol.
    Logs the entry name to stderr for visibility.
    """
    pdf_bytes = z.read(entry)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        tmp = f.name
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", tmp, "-"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            sys.stderr.write(f"  pdftotext failed on {entry} (rc={result.returncode})\n")
            return ""
        out = result.stdout
    finally:
        os.unlink(tmp)
    return out[:max_chars] if len(out) > max_chars else out


def _bairro_text(row, max_chars):
    proto = _protocol(row)
    z, idx = _open_zip("bairro_municipio_2024.zip")
    if proto not in idx:
        return ""
    return _pdf_to_text(z, idx[proto], max_chars)


def _bairro_user_prompt(row, text, template):
    return template.format(
        protocol=_protocol(row),
        municipality=str(row.get("NM_UE") or ""),
        uf=str(row["SG_UF"]),
        institute=str(row.get("NM_EMPRESA") or ""),
        pdf_text=text,
    )


def _questionario_text(row, max_chars):
    proto = _protocol(row)
    z, idx = _open_zip("questionario_pesquisa_2024.zip")
    if proto not in idx:
        return ""
    return _pdf_to_text(z, idx[proto], max_chars)


def _questionario_user_prompt(row, text, template):
    return template.format(
        protocol=_protocol(row),
        municipality=str(row.get("NM_UE") or ""),
        uf=str(row["SG_UF"]),
        institute=str(row.get("NM_EMPRESA") or ""),
        pdf_text=text,
    )


TASKS = [
    TaskSpec("sampling", poll_sampling, PollSampling,
             build_text=_sampling_text,
             build_user_prompt=_sampling_user_prompt,
             build_doc_id=_protocol),
    TaskSpec("coverage", poll_coverage, PollCoverage,
             build_text=_coverage_text,
             build_user_prompt=_coverage_user_prompt,
             build_doc_id=_protocol),
    TaskSpec("operations", poll_operations, PollOperations,
             build_text=_operations_text,
             build_user_prompt=_operations_user_prompt,
             build_doc_id=_protocol),
    TaskSpec("bairro_detail", poll_bairro_detail, PollBairroDetail,
             build_text=_bairro_text,
             build_user_prompt=_bairro_user_prompt,
             build_doc_id=_protocol,
             max_tokens_override=8000),
    TaskSpec("questionario", poll_questionario, PollQuestionario,
             build_text=_questionario_text,
             build_user_prompt=_questionario_user_prompt,
             build_doc_id=_protocol,
             max_tokens_override=8000),
]


# ── State file ──────────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def _save_state(s: dict):
    STATE_PATH.write_text(json.dumps(s, indent=2))


# ── Build phase ─────────────────────────────────────────────────────

def _build_request(task: TaskSpec, row: pd.Series) -> dict | None:
    text = task.build_text(row, task.max_chars)
    if len(text.strip()) < task.min_chars:
        return None
    doc_id = task.build_doc_id(row)
    t_hash = text_hash(text)
    key = task.cache.key(doc_id, t_hash, MODEL, schema_name=task.schema.schema_name)
    # Already cached → skip
    if task.cache.get(key) is not None:
        return None
    user_prompt = task.build_user_prompt(row, text, task.user_template)
    response_format = type_to_response_format_param(task.schema)
    return {
        "custom_id": f"{task.name}::{doc_id}::{t_hash}",
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": task.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": response_format,
            "temperature": TEMPERATURE,
            "max_tokens": task.max_tokens,
        },
    }


def _short_circuit_coverage_cache(df: pd.DataFrame, cov_task: TaskSpec) -> int:
    """Write deterministic cache entries for non-substantive coverage
    polls so they're treated as cached during build and downstream."""
    n_written = 0
    for _, row in df.iterrows():
        bucket = row["_cov_bucket"]
        if bucket == "substantive":
            continue
        text = _coverage_text(row, cov_task.max_chars)
        doc_id = _protocol(row)
        t_hash = text_hash(text)
        key = cov_task.cache.key(doc_id, t_hash, MODEL, schema_name=PollCoverage.schema_name)
        if cov_task.cache.get(key) is not None:
            continue
        rec = deterministic_coverage_record(bucket, row.get("DS_DADO_MUNICIPIO", ""))
        cov_task.cache.put(
            key, rec,
            doc_id=doc_id, text_hash=t_hash,
            messages=[],
            prompt_hash=cov_task.system_prompt_hash,
            model="deterministic",
            schema_name=PollCoverage.schema_name,
            schema_version=PollCoverage.schema_version,
            validation_status="valid",
            api_params={"response_format": "deterministic_short_circuit", "bucket": bucket},
        )
        n_written += 1
    return n_written


def cmd_build(n: int | None, seed: int, max_mb: float) -> int:
    print(f"[1/3] Load universe")
    df = load_universe()
    print(f"      {len(df):,} mayor polls")
    if n is not None and n < len(df):
        df = df.sample(n=n, random_state=seed).reset_index(drop=True)
        print(f"      subset to {len(df):,} (seed={seed})")

    print(f"[2/3] Apply deterministic coverage short-circuit")
    df["_cov_bucket"] = df["DS_DADO_MUNICIPIO"].apply(coverage_bucket)
    bc = df["_cov_bucket"].value_counts().to_dict()
    for b, c in bc.items():
        print(f"      {b:25s} {c:5,d}")
    cov_task = next(t for t in TASKS if t.name == "coverage")
    n_short = _short_circuit_coverage_cache(df, cov_task)
    print(f"      wrote {n_short:,} deterministic coverage cache entries")

    print(f"[3/3] Build batch JSONLs per task (auto-chunk at ~{max_mb} MB)")
    counts = {}
    # Clear any previous part files for these tasks
    for task in TASKS:
        for old in BATCH_DIR.glob(f"requests_{task.name}__part*.jsonl"):
            old.unlink()
    for task in TASKS:
        candidates = df if task.name != "coverage" else df[df["_cov_bucket"] == "substantive"]
        n_total = n_cached = n_skipped = n_queued = 0
        # Chunking: open part0 first; switch to next part when current
        # exceeds max_mb. Each part stays comfortably under the 200 MB
        # batch input cap.
        part_idx = 0
        current_path = BATCH_DIR / f"requests_{task.name}__part{part_idx:02d}.jsonl"
        f = current_path.open("w", encoding="utf-8")
        parts = [(part_idx, current_path)]
        max_bytes = int(max_mb * 1_000_000)
        try:
            for _, row in candidates.iterrows():
                n_total += 1
                text = task.build_text(row, task.max_chars)
                if len(text.strip()) < task.min_chars:
                    n_skipped += 1
                    continue
                doc_id = task.build_doc_id(row)
                t_hash = text_hash(text)
                key = task.cache.key(doc_id, t_hash, MODEL, schema_name=task.schema.schema_name)
                if task.cache.get(key) is not None:
                    n_cached += 1
                    continue
                req = _build_request(task, row)
                if req is None:
                    n_skipped += 1
                    continue
                line = json.dumps(req, ensure_ascii=False) + "\n"
                # Roll over to next part if this line would push us over the cap
                if f.tell() + len(line.encode("utf-8")) > max_bytes:
                    f.close()
                    part_idx += 1
                    current_path = BATCH_DIR / f"requests_{task.name}__part{part_idx:02d}.jsonl"
                    f = current_path.open("w", encoding="utf-8")
                    parts.append((part_idx, current_path))
                f.write(line)
                n_queued += 1
        finally:
            f.close()
        # Drop empty trailing files
        for idx, p in list(parts):
            if p.exists() and p.stat().st_size == 0:
                p.unlink()
                parts = [(i, x) for i, x in parts if x != p]
        sizes = [p.stat().st_size / 1e6 for _, p in parts]
        print(f"  [{task.name}] total={n_total:,}  cached={n_cached:,}  "
              f"skipped={n_skipped:,}  queued={n_queued:,}  → "
              f"{len(parts)} part(s), {sum(sizes):.1f} MB")
        counts[task.name] = dict(total=n_total, cached=n_cached,
                                  skipped=n_skipped, queued=n_queued,
                                  parts=[{"part": i, "bytes": p.stat().st_size}
                                         for i, p in parts])

    summary_path = BATCH_DIR / "build_summary.json"
    summary_path.write_text(json.dumps({"subset_n": n, "seed": seed,
                                        "coverage_buckets": bc,
                                        "n_short_circuit_coverage": n_short,
                                        "per_task": counts}, indent=2))
    print(f"      summary → {summary_path}")
    return 0


# ── Submit phase ────────────────────────────────────────────────────

def _task_parts(task: TaskSpec) -> list[Path]:
    """All chunk JSONLs for a task, in part order."""
    return sorted(BATCH_DIR.glob(f"requests_{task.name}__part*.jsonl"))


def cmd_submit() -> int:
    state = _load_state()
    client = openai.OpenAI()
    for task in TASKS:
        parts = _task_parts(task)
        if not parts:
            print(f"  [{task.name}] no requests to submit")
            continue
        task_state = state.setdefault(task.name, {})
        for path in parts:
            key = path.stem.split("__")[-1]  # "part00"
            if task_state.get(key, {}).get("batch_id"):
                print(f"  [{task.name}/{key}] already submitted as "
                      f"{task_state[key]['batch_id']} — skipping")
                continue
            print(f"  [{task.name}/{key}] uploading {path.name} "
                  f"({path.stat().st_size/1e6:.1f} MB)")
            f = client.files.create(file=open(path, "rb"), purpose="batch")
            b = client.batches.create(
                input_file_id=f.id,
                endpoint="/v1/chat/completions",
                completion_window="24h",
                metadata={"task": task.name, "part": key,
                          "submitted_by": "extract_methodology_batch.py"},
            )
            task_state[key] = {
                "batch_id": b.id,
                "input_file_id": f.id,
                "submitted_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "status": b.status,
            }
            print(f"  [{task.name}/{key}] batch {b.id} created (status={b.status})")
    _save_state(state)
    return 0


# ── Status phase ────────────────────────────────────────────────────

def cmd_status() -> int:
    state = _load_state()
    if not state:
        print("No batches submitted yet.")
        return 0
    client = openai.OpenAI()
    for task in TASKS:
        task_state = state.get(task.name) or {}
        for key, s in task_state.items():
            if not s.get("batch_id"):
                continue
            b = client.batches.retrieve(s["batch_id"])
            rc = b.request_counts
            print(f"  [{task.name}/{key}] {b.id}: {b.status}  "
                  f"({rc.completed}/{rc.total} completed, {rc.failed} failed)")
            s["status"] = b.status
            if b.output_file_id:
                s["output_file_id"] = b.output_file_id
            if b.error_file_id:
                s["error_file_id"] = b.error_file_id
    _save_state(state)
    return 0


# ── Harvest phase ───────────────────────────────────────────────────

def _write_cache_from_batch_line(task: TaskSpec, line: str) -> tuple[bool, str]:
    """Parse one batch output line and write to the llmkit cache.
    Returns (success, reason)."""
    entry = json.loads(line)
    custom_id = entry.get("custom_id", "")
    parts = custom_id.split("::")
    if len(parts) != 3:
        return False, f"bad custom_id {custom_id!r}"
    _task_name, doc_id, t_hash = parts
    if entry.get("error"):
        return False, f"error response: {entry['error']}"
    body = entry.get("response", {}).get("body") or {}
    choices = body.get("choices") or []
    if not choices:
        return False, "no choices"
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if not content:
        return False, f"empty content (refusal={msg.get('refusal')})"
    try:
        extraction = json.loads(content)
    except json.JSONDecodeError as e:
        return False, f"json decode: {e}"
    key = task.cache.key(doc_id, t_hash, MODEL, schema_name=task.schema.schema_name)
    usage = body.get("usage") or {}
    task.cache.put(
        key, extraction,
        doc_id=doc_id, text_hash=t_hash,
        messages=[],  # batch output doesn't echo back input; audit lives in build_*.jsonl
        prompt_hash=task.system_prompt_hash,
        model=MODEL,
        model_version=body.get("model", ""),
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        finish_reason=choices[0].get("finish_reason", ""),
        schema_name=task.schema.schema_name,
        schema_version=task.schema.schema_version,
        validation_status="batch",
        usage={"prompt_tokens": usage.get("prompt_tokens", 0),
               "completion_tokens": usage.get("completion_tokens", 0)},
        api_params={"response_format": "structured_outputs_batch",
                    "schema_name": task.schema.schema_name},
    )
    return True, ""


def cmd_harvest() -> int:
    state = _load_state()
    client = openai.OpenAI()
    for task in TASKS:
        task_state = state.get(task.name) or {}
        for key, s in task_state.items():
            bid = s.get("batch_id")
            if not bid:
                continue
            b = client.batches.retrieve(bid)
            if b.status != "completed":
                print(f"  [{task.name}/{key}] not completed (status={b.status})")
                continue
            if not b.output_file_id:
                print(f"  [{task.name}/{key}] no output file")
                continue
            out_path = BATCH_DIR / f"output_{task.name}__{key}.jsonl"
            print(f"  [{task.name}/{key}] downloading output → {out_path}")
            content = client.files.content(b.output_file_id).text
            out_path.write_text(content, encoding="utf-8")
            n_ok = n_err = 0
            errs = []
            for line in content.splitlines():
                ok, reason = _write_cache_from_batch_line(task, line)
                if ok: n_ok += 1
                else:
                    n_err += 1
                    if len(errs) < 5: errs.append(reason)
            print(f"    wrote {n_ok:,} cache entries, {n_err} errors")
            if errs: print(f"    sample errors: {errs}")
            s["harvested_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            s["n_cached"] = n_ok
            s["n_errors"] = n_err
    _save_state(state)
    return 0


# ── Entry point ─────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_build = sub.add_parser("build")
    p_build.add_argument("--n", type=int, default=None)
    p_build.add_argument("--all", action="store_true")
    p_build.add_argument("--seed", type=int, default=42)
    p_build.add_argument("--max-mb", type=float, default=180.0,
                         help="Auto-split JSONL files above this size (batch limit is 200 MB).")
    sub.add_parser("submit")
    sub.add_parser("status")
    sub.add_parser("harvest")
    args = ap.parse_args()
    if args.cmd == "build":
        return cmd_build(n=None if args.all else args.n, seed=args.seed, max_mb=args.max_mb)
    if args.cmd == "submit": return cmd_submit()
    if args.cmd == "status": return cmd_status()
    if args.cmd == "harvest": return cmd_harvest()
    return 1


if __name__ == "__main__":
    sys.exit(main())
