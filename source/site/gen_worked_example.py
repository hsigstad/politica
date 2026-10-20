#!/usr/bin/env python3
# INTENT: regenerate the committed worked-example site assets
# (source/site/worked_example/<task>.json) by running the v2 Panel-B extractors
# on ONE example protocol and pinning, per task, the exact input document sent +
# the real v2 output + token usage + the JSON schema. The site hook
# (_render_worked_example in site.py) renders these alongside the live prompt
# .txt files into source/llm/worked-example.html.
# REASONING: the page must show the LATEST (v2) prompts next to a REAL output, so
# the output has to come from a fresh v2 run (the old poll-sponsor-bias pilot
# cache is v1 and would contradict the v2 schema). Assets are committed so the
# site builds without raw data or an LLM key (same pattern as the summary cache).
# ASSUMES: OPENAI_API_KEY set; example data under build/scrape/tse_polls_2024/;
# llmkit importable. This makes LLM calls — run deliberately, not in the site build.
# Usage: PYTHONPATH=/workspace/packages/llmkit:source/llm BASE_DIR=$PWD \
#        python3 source/site/gen_worked_example.py
import json, os, sys, zipfile, subprocess, tempfile
from pathlib import Path
import pandas as pd

BASE = Path(os.environ.get("BASE_DIR", Path(__file__).resolve().parents[2]))
sys.path.insert(0, "/workspace/packages/llmkit")
sys.path.insert(0, str(BASE / "source" / "llm"))

import openai
from llmkit import LLMCache
import schemas
from poll_questionario import extract_poll_questionario
from poll_sampling import extract_poll_sampling
from poll_weighting import extract_poll_weighting
from poll_bairro_detail import extract_poll_bairro_detail

PROTO = "SP076792024"  # Ilhabela, Instituto Paraná — Panel-B dev-set target
SCRAPE = BASE / "build" / "scrape" / "tse_polls_2024"
OUT = BASE / "source" / "site" / "worked_example"
CACHE = BASE / "build" / "llm" / "worked_example_cache"
OUT.mkdir(parents=True, exist_ok=True)
client = openai.OpenAI()

# task -> (schema class, prompt stem, page title)
META = {
    "questionario":  ("PollQuestionario",  "poll_questionario",
                      "Questionnaire (questionario_pesquisa PDF)"),
    "sampling":      ("PollSampling",       "poll_sampling",
                      "Sampling design (DS_ registration fields)"),
    "weighting":     ("PollWeighting",      "poll_weighting",
                      "Post-fielding weighting (DS_ registration fields)"),
    "bairro_detail": ("PollBairroDetail",   "poll_bairro_detail",
                      "Bairro/coverage detail (bairro_municipio PDF)"),
}


def pdf_bytes_and_text(zipname):
    zf = zipfile.ZipFile(SCRAPE / zipname)
    entry = next(n for n in zf.namelist() if os.path.basename(n).startswith(PROTO))
    b = zf.read(entry)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b); tmp = f.name
    txt = subprocess.run(["pdftotext", "-layout", tmp, "-"],
                         capture_output=True, text=True).stdout
    os.unlink(tmp)
    return entry, b, txt.strip()


def dump(task, input_source, input_doc, result):
    clsname, stem, title = META[task]
    cls = getattr(schemas, clsname)
    rec = {
        "task": task, "title": title, "protocol": PROTO, "model": "gpt-4o-mini",
        "schema_class": clsname, "prompt_stem": stem,
        "input_source": input_source, "input_doc": input_doc,
        "valid": bool(result and result.valid),
        "output": (result.parsed.model_dump(mode="json")
                   if result and result.parsed else (result.raw if result else None)),
        "usage": (result.usage if result else {}),
        "schema_json": json.dumps(cls.model_json_schema(), ensure_ascii=False, indent=2),
    }
    (OUT / f"{task}.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    comp = (result.usage or {}).get("completion_tokens") if result else None
    print(f"  {task}: valid={rec['valid']} completion_tokens={comp}")


def main():
    # Optional CLI task filter: `gen_worked_example.py bairro_detail sampling`
    # regens only those sections; no args = all. Lets a single changed
    # extractor be refreshed without re-running (and perturbing) the others.
    tasks = set(sys.argv[1:]) or set(META)
    unknown = tasks - set(META)
    if unknown:
        raise SystemExit(f"unknown task(s): {sorted(unknown)}; valid: {sorted(META)}")

    sp = pd.read_csv(SCRAPE / "pesquisa_eleitoral_2024_SP.csv", sep=";",
                     encoding="latin-1", dtype=str, on_bad_lines="skip")
    row = sp[sp["NR_PROTOCOLO_REGISTRO"] == PROTO].iloc[0]
    uf = str(row["SG_UF"]); inst = str(row.get("NM_EMPRESA") or "")
    muni = str(row.get("NM_UE") or "")
    ds_met = str(row.get("DS_METODOLOGIA_PESQUISA") or "")
    ds_pla = str(row.get("DS_PLANO_AMOSTRAL") or "")
    ds_sis = str(row.get("DS_SISTEMA_CONTROLE") or "")
    print(f"Running v2 extractors on {PROTO} ({muni}, {inst}) for: {sorted(tasks)}")

    if "questionario" in tasks:
        q_entry, q_bytes, q_text = pdf_bytes_and_text("questionario_pesquisa_2024.zip")
        dump("questionario", q_entry, q_text, extract_poll_questionario(
            protocol=PROTO, pdf_bytes=q_bytes, municipality=muni, uf=uf, institute=inst,
            client=client, cache=LLMCache(CACHE / "questionario"), reextract=True))

    if "sampling" in tasks:
        dump("sampling", "DS_METODOLOGIA_PESQUISA + DS_PLANO_AMOSTRAL",
             ds_met + "\n\n" + ds_pla, extract_poll_sampling(
                 protocol=PROTO, uf=uf, institute=inst, ds_metodologia=ds_met,
                 ds_plano_amostral=ds_pla, client=client,
                 cache=LLMCache(CACHE / "sampling"), reextract=True))

    if "weighting" in tasks:
        dump("weighting", "DS_METODOLOGIA_PESQUISA + DS_PLANO_AMOSTRAL + DS_SISTEMA_CONTROLE",
             ds_met + "\n\n" + ds_pla + "\n\n" + ds_sis, extract_poll_weighting(
                 protocol=PROTO, ds_metodologia=ds_met, ds_plano_amostral=ds_pla,
                 ds_sistema_controle=ds_sis, uf=uf, institute=inst, client=client,
                 cache=LLMCache(CACHE / "weighting"), reextract=True))

    if "bairro_detail" in tasks:
        try:
            b_entry, b_bytes, b_text = pdf_bytes_and_text("bairro_municipio_2024.zip")
            dump("bairro_detail", b_entry, b_text, extract_poll_bairro_detail(
                protocol=PROTO, pdf_bytes=b_bytes, municipality=muni, uf=uf, institute=inst,
                client=client, cache=LLMCache(CACHE / "bairro"), reextract=True))
        except StopIteration:
            print("  bairro_detail: no PDF for this protocol — skipping")
    print("DONE")


if __name__ == "__main__":
    raise SystemExit(main())
