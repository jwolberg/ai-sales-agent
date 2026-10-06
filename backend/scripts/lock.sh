#!/usr/bin/env sh
# Regenerate the pinned lockfiles in requirements/ from pyproject.toml (pip-tools).
# dev-voice.txt is the superset; prod.txt and dev.txt are compiled against it as a constraint so
# every shared package resolves to the same version in all three. Run from backend/ with the venv
# that has the dev extra installed. Pass --upgrade to bump everything to the latest allowed.
set -eu
cd "$(dirname "$0")/.."
compile() { pip-compile --quiet --strip-extras --no-emit-index-url "$@"; }
compile "$@" --extra dev --extra voice -o requirements/dev-voice.txt pyproject.toml
compile --extra voice -c requirements/dev-voice.txt -o requirements/prod.txt pyproject.toml
compile --extra dev -c requirements/dev-voice.txt -o requirements/dev.txt pyproject.toml
echo "lockfiles updated: requirements/{dev-voice,prod,dev}.txt"
