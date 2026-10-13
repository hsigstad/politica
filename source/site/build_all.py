# INTENT: thin shim that hands politica's SiteConfig to the shared sitekit
# renderer. All rendering/nav/link machinery lives in research-kit/sitekit; this
# file only wires the import path (the educloud system venv is read-only, so the
# sys.path shim replaces `pip install -e`).
import sys
from pathlib import Path

_SITEKIT = (
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "research-kit" / "sitekit"
)
if str(_SITEKIT) not in sys.path:
    sys.path.insert(0, str(_SITEKIT))

from sitekit import build_site
from source.site.site import config

if __name__ == "__main__":
    raise SystemExit(build_site(config))
