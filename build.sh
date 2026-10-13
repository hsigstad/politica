#!/bin/bash
# Build + deploy the politica data portal (UNGATED / plaintext).
#
# Usage:
#   bash build.sh summary [--force]  # (re)compute the per-dataset summary cache
#   bash build.sh site               # build static site in build/site/
#   bash build.sh deploy             # build + push to hsigstad/politica gh-pages
#   bash build.sh push               # deploy already-built build/site/ (no rebuild)
#
# The site is PLAINTEXT (SITE_GATED=0): politica is a PUBLIC repo
# (github.com/hsigstad/politica) over public TSE open data. Individual CPFs and
# titulos eleitorais are masked in the summary cache (source/summary/config.py
# mask_columns), so no PII is surfaced.
#
# The summary cache (source/summary/cache/*.json) is committed to git (it lives
# outside the gitignored build/), so `site` and `deploy` build WITHOUT the clean
# tables. Refresh it with `bash build.sh summary --force` on a host that has the
# clean tables staged, then commit the JSONs.
#
# Deploy requirement: git push access to hsigstad/politica.

set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

export SITE_GATED=0
SITE_TITLE="politica"
source "$PROJECT_DIR/../../research-kit/tools/site_deploy.sh"

MODE="${1:-site}"
shift || true

build_site() {
    cd "$PROJECT_DIR"
    echo "=== Building data portal (sitekit empirical archetype) ==="
    python3 -m source.site.build_all
}

case "$MODE" in
    summary) cd "$PROJECT_DIR"; python3 -m source.summary.build_all "$@" ;;
    site)    build_site ;;
    deploy)  build_site; sk_deploy_site ;;
    push)    sk_deploy_site ;;
    *) echo "Usage: bash build.sh [summary|site|deploy|push]"; exit 1 ;;
esac
