"""politica path configuration.

Reads paths from `.env` at the project root. Adds path-shaped helpers
for the build subtree (used by source/scrape, source/llm, source/clean).

Environment
-----------
BASE_DIR        Absolute path to the politica project root.
DATA_DIR        Absolute path to the shared TSE data root
                (e.g. $DATA_DIR).
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Resolve BASE_DIR — prefer env, fall back to the directory holding this file.
PROJECT_ROOT = Path(os.environ.get(
    "BASE_DIR", str(Path(__file__).resolve().parent)
))

# Source-search paths used by the existing clean scripts.
sys.path.append(str(PROJECT_ROOT / "source" / "clean"))
sys.path.append(str(PROJECT_ROOT / "source" / "insert"))

# Build subtree (used by scrape / llm / clean / assemble scripts).
BUILD_DIR = PROJECT_ROOT / "build"
build_scrape_dir = BUILD_DIR / "scrape"
build_llm_dir = BUILD_DIR / "llm"
build_clean_dir = BUILD_DIR / "clean"

# Shared TSE data root. Some legacy clean scripts compare data_dir as a
# string with os.path.join(); expose as both a Path (preferred) and the
# underlying string under data_dir_str for backwards compatibility.
data_dir = Path(os.environ["DATA_DIR"])
data_dir_str = os.environ["DATA_DIR"]

# 2024 TSE poll registration CSVs. 2026-05-28: SP-slice pilot rclones
# these to build/scrape/tse_polls_2024 (workspace-local, visible from
# the sandbox). Move to `data_dir / "tse_polls_2024"` after the
# pilot is stable; both consumers (source/scrape/tse_relatorio.py,
# source/clean/poll_2024.py) reference this single attribute so the
# migration is a one-line edit here.
tse_polls_2024_dir = build_scrape_dir / "tse_polls_2024"

