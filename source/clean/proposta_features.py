"""Clean: proposta de governo text features (no LLM).

INTENT. A panel-ready feature table off `proposta_governo.parquet`, one row
per (year, estado, SQ_CANDIDATO), holding everything about a plan that is
cheap and deterministic to compute: size, which policy areas it covers, and
whether it is a copy of another candidate's plan. These are the variables a
downstream regression can use directly, and the duplicate flags are both a
data-quality caveat and a research object (Brazilian planos de governo are
widely copied from party templates and each other). The substantive
"what did they promise" extraction is a separate LLM step; this table needs
no API calls.

REASONING. The text is semi-structured, not templated: ~90% of plans name
Saúde/Educação but headings, order and numbering vary, so we detect policy
areas by accent-insensitive keyword presence rather than parsing sections.
Duplication comes in two grades: verbatim copies (caught by hashing the
normalized text) and heavy paraphrase / partial reuse (caught by MinHash-LSH
over word-shingles, a scalable approximate-Jaccard cluster). MinHash is
implemented here with numpy (no datasketch dependency) and seeded, so the
build is reproducible.

ASSUMES.
  - Input build/clean/proposta_governo.parquet (see proposta_governo.py).
    Rows whose `text_source` contains `sparse`/`error` have little/no text
    until the OCR pass runs; their area flags will read false and they are
    excluded from duplicate clustering (n_chars < MIN_DEDUP_CHARS).
  - Keyword lists are presence heuristics, not a taxonomy: `has_saude` means
    "mentions health", not "has a health section".
  - Near-dup clusters approximate Jaccard >= NEAR_DUP_THRESHOLD on 5-word
    shingles; `near_dup_id` is an arbitrary cluster label, `near_dup_size`
    its membership count (1 = unique).
"""
import argparse
import hashlib
import re
import zlib
from pathlib import Path

import numpy as np
import pandas as pd
from unidecode import unidecode

import path

IN_DEFAULT = path.build_clean_dir / "proposta_governo.parquet"
OUT_DEFAULT = path.build_clean_dir / "proposta_features.parquet"

# Accent-insensitive keyword presence -> policy-area flag. Keys become the
# `has_<key>` columns. Matched as substrings of the normalized text.
POLICY_AREAS = {
    "saude": ["saude"],
    "educacao": ["educacao", "ensino", "escola"],
    "seguranca": ["seguranca"],
    "infraestrutura": ["infraestrutura", "pavimentacao", "obras publicas"],
    "saneamento": ["saneamento", "esgoto", "agua tratada"],
    "assistencia_social": ["assistencia social"],
    "meio_ambiente": ["meio ambiente", "ambiental", "sustentabil"],
    "cultura": ["cultura"],
    "esporte_lazer": ["esporte", "lazer"],
    "habitacao": ["habitacao", "moradia"],
    "agricultura": ["agricultura", "agropecuaria", "produtor rural"],
    "turismo": ["turismo"],
    "transporte": ["transporte", "mobilidade", "transito"],
    "emprego_renda": ["geracao de emprego", "geracao de renda",
                      "desenvolvimento economico"],
    "saude_mulher": ["direitos da mulher", "politica para as mulheres"],
}

MIN_DEDUP_CHARS = 400   # skip near-empty (scanned/sparse) rows in clustering
SHINGLE_K = 5           # words per shingle
NUM_PERM = 128          # MinHash permutations
LSH_BANDS = 16          # 16 bands x 8 rows -> ~Jaccard 0.71 candidate cutoff
NEAR_DUP_THRESHOLD = 0.70   # refine LSH candidates by estimated Jaccard
_MERSENNE = (1 << 61) - 1

_NONALNUM = re.compile(r"[^0-9a-z ]+")
_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Lowercase, strip accents/punctuation, collapse whitespace."""
    t = _NONALNUM.sub(" ", unidecode(text).lower())
    return _WS.sub(" ", t).strip()


def area_flags(norm: str) -> dict:
    """has_<area> booleans + n_areas for a normalized string."""
    flags = {f"has_{a}": any(kw in norm for kw in kws)
             for a, kws in POLICY_AREAS.items()}
    flags["n_areas"] = sum(flags.values())
    return flags


def _minhash_signature(tokens: list[str], a: np.ndarray,
                       b: np.ndarray) -> np.ndarray | None:
    """MinHash signature (uint64[NUM_PERM]) over word-shingles, or None."""
    if len(tokens) >= SHINGLE_K:
        shingles = {" ".join(tokens[i:i + SHINGLE_K])
                    for i in range(len(tokens) - SHINGLE_K + 1)}
    else:
        shingles = set(tokens)
    if not shingles:
        return None
    # crc32 keeps base hashes < 2^32 so a*h stays inside uint64.
    H = np.fromiter((zlib.crc32(s.encode()) for s in shingles),
                    dtype=np.uint64, count=len(shingles))
    M = (a[:, None] * H[None, :] + b[:, None]) % _MERSENNE
    return M.min(axis=1)


class _Union:
    def __init__(self, n): self.p = list(range(n))
    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]; x = self.p[x]
        return x
    def union(self, x, y):
        rx, ry = self.find(x), self.find(y)
        if rx != ry: self.p[rx] = ry


def near_dup_clusters(norms: list[str], idx: list[int], n_rows: int,
                      seed: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """Return (near_dup_id, near_dup_size) arrays aligned to the full frame.

    `norms`/`idx` are the normalized texts and their row positions for the
    subset dense enough to cluster; every other row is its own singleton.
    """
    rng = np.random.RandomState(seed)
    a = rng.randint(1, 1 << 31, size=NUM_PERM).astype(np.uint64)
    b = rng.randint(0, 1 << 31, size=NUM_PERM).astype(np.uint64)
    rows = LSH_BANDS and NUM_PERM // LSH_BANDS

    sigs, kept = {}, []
    for pos, norm in zip(idx, norms):
        sig = _minhash_signature(norm.split(), a, b)
        if sig is not None:
            sigs[pos] = sig; kept.append(pos)

    # LSH: bucket by each band's signature slice; candidates share a bucket.
    uf = _Union(n_rows)
    buckets: dict[bytes, list[int]] = {}
    for pos in kept:
        sig = sigs[pos]
        for band in range(LSH_BANDS):
            key = bytes([band]) + sig[band * rows:(band + 1) * rows].tobytes()
            buckets.setdefault(key, []).append(pos)
    for members in buckets.values():
        if len(members) < 2:
            continue
        base = members[0]
        for other in members[1:]:
            # Refine: only union if estimated Jaccard clears the threshold.
            if np.mean(sigs[base] == sigs[other]) >= NEAR_DUP_THRESHOLD:
                uf.union(base, other)

    near_id = np.arange(n_rows)
    for pos in kept:
        near_id[pos] = uf.find(pos)
    # Relabel roots to compact ids and count sizes.
    _, inv, counts = np.unique(near_id, return_inverse=True, return_counts=True)
    return inv.astype(np.int64), counts[inv].astype(np.int64)


def build(df: pd.DataFrame, near_dup: bool = True) -> pd.DataFrame:
    print(f"Normalizing {len(df):,} plans")
    norms = [normalize(t) if isinstance(t, str) else "" for t in df["text"]]

    feats = pd.DataFrame([area_flags(n) for n in norms], index=df.index)
    out = df[["year", "estado", "SQ_CANDIDATO", "n_docs", "n_pages",
              "n_chars", "text_source"]].copy()
    out["n_words"] = [len(n.split()) for n in norms]
    out = pd.concat([out, feats], axis=1)

    # Exact duplicates: hash of normalized text.
    def _h(n):
        return hashlib.blake2b(n.encode(), digest_size=16).hexdigest() if n else ""
    out["norm_hash"] = [_h(n) for n in norms]
    counts = out["norm_hash"].map(out["norm_hash"].value_counts())
    out["exact_dup_size"] = counts.where(out["norm_hash"] != "", 1).astype(int)
    out["is_exact_dup"] = out["exact_dup_size"] > 1

    if near_dup:
        pos = np.arange(len(df))
        dense = out["n_chars"].to_numpy() >= MIN_DEDUP_CHARS
        idx = pos[dense].tolist()
        print(f"MinHash-LSH clustering {len(idx):,} plans "
              f">= {MIN_DEDUP_CHARS} chars")
        near_id, near_size = near_dup_clusters(
            [norms[i] for i in idx], idx, len(df))
        out["near_dup_id"] = near_id
        out["near_dup_size"] = near_size
        out["is_near_dup"] = out["near_dup_size"] > 1

    return out.reset_index(drop=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="inp", type=Path, default=IN_DEFAULT)
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    ap.add_argument("--uf", help="restrict to one UF (smoke test)")
    ap.add_argument("--no-near-dup", dest="near_dup", action="store_false")
    args = ap.parse_args()

    df = pd.read_parquet(args.inp)
    if args.uf:
        df = df[df["estado"] == args.uf.upper()].reset_index(drop=True)
    out = build(df, near_dup=args.near_dup)

    n = len(out)
    print(f"\n{n:,} plans")
    print(f"  mean policy areas covered: {out['n_areas'].mean():.1f}")
    print(f"  exact duplicates: {int(out['is_exact_dup'].sum()):,} "
          f"({out['is_exact_dup'].mean()*100:.1f}%)")
    if args.near_dup:
        print(f"  in a near-dup cluster: {int(out['is_near_dup'].sum()):,} "
              f"({out['is_near_dup'].mean()*100:.1f}%)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.out, engine="pyarrow", index=False, compression="zstd")
    print(f"Wrote {n:,} rows to {args.out}")
