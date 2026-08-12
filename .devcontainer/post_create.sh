#!/usr/bin/env bash
set -euo pipefail

# The scrubber core (scripts/warden.py, scripts/llm.py, scripts/unicode_scrub.py)
# is stdlib-only. This venv exists for the one optional dependency, tiktoken,
# which only makes the divergence metric more faithful.
python3 -m venv .venv
.venv/bin/pip install --upgrade --quiet pip
.venv/bin/pip install --quiet -r requirements.txt

# Formatting tooling (black) plus the pre-commit runner. Installing pre-commit
# into .venv and calling it by path makes the generated .git/hooks/pre-commit
# point at .venv/bin/python, so commits work without an activated virtualenv.
.venv/bin/pip install --quiet -r requirements-dev.txt
.venv/bin/pre-commit install

# Deliberately NOT installed: requirements-stego.txt (torch + transformers,
# several GB), needed only for the scripts/stego.py demo. To get it:
#   .venv/bin/pip install -r requirements-stego.txt
echo "ready: .venv/bin/python; stego demo deps not installed (see requirements-stego.txt)"
