#!/usr/bin/env bash
# Полный прогон: все колоды проекта, оба канала, затем сравнение по каждой колоде.
# Запуск: CORPUS_ROOT=/path/to/project bash run_all.sh   (или из корня проекта)
set -u
SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
cd "${CORPUS_ROOT:-$PWD}" || exit 1
DECKS="${DECKS:-$(ls -d decks/*/ 2>/dev/null | xargs -n1 basename)}"
if [ -z "$DECKS" ]; then
  echo "не нашёл колод в $(pwd)/decks"
  exit 2
fi
for deck in $DECKS; do
  for backend in ${BACKENDS:-zcode ollama}; do
    echo "=== $deck / $backend ==="
    python3 "$SCRIPTS/run_analysis.py" --backend "$backend" --deck "$deck" || echo "  сбой $deck/$backend"
  done
  python3 "$SCRIPTS/compare_analyses.py" "$deck"
done
echo "=== готово ==="
