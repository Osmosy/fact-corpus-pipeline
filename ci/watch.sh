#!/usr/bin/env bash
# Локальная проверка origin/main без записи в git: только отчёт.
#
# Нужен, когда Actions недоступны (кончились минуты, workflow отключён) и хочется знать
# состояние удалённой ветки, не дожидаясь веб-интерфейса. Ничего не коммитит и не пушит —
# это важно: проверка не должна менять то, что проверяет.
#
# Использование: ci/watch.sh [путь-к-репозиторию]
# Код выхода: 0 — чисто, 1 — находки, 2 — не смог проверить.
set -u
REPO="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$REPO" || exit 2

if git remote get-url origin >/dev/null 2>&1; then
  git fetch -q origin main 2>/dev/null || { echo "не удалось получить origin/main"; exit 2; }
  SHA="$(git rev-parse --short origin/main)"
else
  SHA="$(git rev-parse --short HEAD)"
fi

if OUT="$(python3 ci/selfcheck.py 2>&1)"; then
  echo "origin/main@$SHA: самопроверка чиста"
  exit 0
fi

echo "origin/main@$SHA: находки"
echo "$OUT"
exit 1
