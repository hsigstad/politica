"""Subdir path shim — forwards everything from the project's top-level
path.py so scripts in source/clean/ get the full BUILD_DIR helpers
when they ``import path``. Python's import resolution finds this
file first when scripts in source/clean/ do ``import path`` (because
the top-level path.py appends source/clean/ to sys.path).
"""

import os
import sys
from pathlib import Path

# Locate top-level politica root — prefer BASE_DIR from .env, fall
# back to walking up from this file.
_BASE = Path(
    os.environ.get("BASE_DIR")
    or str(Path(__file__).resolve().parents[2])
)
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

# Forward all top-level path.py attributes (data_dir, BUILD_DIR,
# build_scrape_dir, build_llm_dir, build_clean_dir, tse_polls_2024_dir, ...).
# We reload the top-level module by absolute path to avoid recursive
# resolution into this shim.
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("_politica_path_top", str(_BASE / "path.py"))
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
for _name in dir(_mod):
    if not _name.startswith("_"):
        globals()[_name] = getattr(_mod, _name)
