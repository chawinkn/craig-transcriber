#!/usr/bin/env bash
# scripts/check.sh                 check the whole repo (CI)
# scripts/check.sh --fix [files…]  format and fix the files (the whole repo if none), then check them
set -euo pipefail
cd "$(dirname "$0")/.."

if command -v ruff >/dev/null; then ruff=(ruff)
elif [ -x .venv/bin/ruff ]; then ruff=(.venv/bin/ruff)
else ruff=(python3 -m ruff)
fi
biome=(npx --yes @biomejs/biome@2.5.15)

fix=
if [ "${1:-}" = --fix ]; then fix=1; shift; fi
if [ -z "$fix" ] && [ $# -gt 0 ]; then echo "usage: scripts/check.sh [--fix [files...]]" >&2; exit 2; fi

py=() web=()
for f in "$@"; do
  case "$f" in
    src/craig_transcriber/static/*.js | src/craig_transcriber/static/*.css) web+=("$f") ;;
    *.py) py+=("$f") ;;
  esac
done
scoped=$(( ${#py[@]} + ${#web[@]} ))
if [ $# -gt 0 ] && [ "$scoped" -eq 0 ]; then exit 0; fi
if [ "$scoped" -eq 0 ]; then py=(src tests scripts) web=(src/craig_transcriber/static); fi

status=0
step() { echo "== $*"; "$@" || status=1; }

if [ ${#py[@]} -gt 0 ]; then
  if [ -n "$fix" ]; then
    "${ruff[@]}" format "${py[@]}"
    "${ruff[@]}" check --fix "${py[@]}" || true
  fi
  step "${ruff[@]}" format --check "${py[@]}"
  step "${ruff[@]}" check "${py[@]}"
fi
if [ ${#web[@]} -gt 0 ]; then
  if [ -n "$fix" ]; then "${biome[@]}" check --write "${web[@]}" || true; fi
  step "${biome[@]}" ci "${web[@]}"
fi
if [ -f scripts/no_history_comments.py ]; then
  if [ "$scoped" -gt 0 ]; then step python3 -I scripts/no_history_comments.py "${py[@]}" "${web[@]}"
  else step python3 -I scripts/no_history_comments.py; fi
fi
exit $status
