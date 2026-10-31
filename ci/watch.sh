#!/usr/bin/env bash
# Самопроверка на каждый новый коммит в origin/main — без GitHub Actions.
#
# Зачем: токен, которым ведётся репозиторий, не имеет scope `workflow`, поэтому файл
# .github/workflows/ci.yml отправить нельзя (GitHub отклоняет пуш). Пока так, проверка
# выполняется локально по расписанию, а результат фиксируется в ci/last-run.json —
# один коммит на смену состояния, не на каждый прогон.
#
# Использование: ci/watch.sh [путь-к-репозиторию]
# Код выхода: 0 — проверка прошла, 1 — находки, 2 — не смог проверить.
set -u
REPO="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$REPO" || exit 2

git fetch -q origin main 2>/dev/null || { echo "не удалось получить origin/main"; exit 2; }
SHA="$(git rev-parse origin/main)"

OUT="$(python3 ci/selfcheck.py 2>&1)"
RC=$?
STATE=$([ "$RC" -eq 0 ] && echo success || echo failure)
STAMP="$(date -Iseconds)"

PREV="$(python3 - <<'PY' 2>/dev/null || true
import json
try:
    d = json.load(open("ci/last-run.json"))
    print(f"{d.get('sha','')} {d.get('state','')}")
except Exception:
    pass
PY
)"
if [ "$PREV" = "$SHA $STATE" ]; then
  # состояние уже зафиксировано в прошлый раз — молчим, чтобы не повторять алерт
  exit 0
fi

python3 - "$SHA" "$STATE" "$STAMP" "$OUT" <<'PY'
import json, sys
sha, state, stamp, out = sys.argv[1:5]
data = {
    "sha": sha,
    "state": state,
    "checked_at": stamp,
    "checker": "ci/selfcheck.py",
    "summary": out.strip().splitlines()[:20],
    "note": "GitHub Actions недоступен: у токена нет scope workflow. Проверка идёт на машине автора.",
}
open("ci/last-run.json", "w", encoding="utf-8").write(
    json.dumps(data, ensure_ascii=False, indent=2) + "\n")
PY

git add ci/last-run.json
git -c user.name="selfcheck" -c user.email="selfcheck@users.noreply.github.com" \
    commit -q -m "ci: $STATE для ${SHA:0:8}" || { echo "нечего коммитить"; exit $([ "$RC" -eq 0 ] && echo 0 || echo 1); }
git push -q origin HEAD:main || echo "коммит сделан, но пуш не прошёл"
echo "записано: $SHA $STATE"
exit $([ "$RC" -eq 0 ] && echo 0 || echo 1)
