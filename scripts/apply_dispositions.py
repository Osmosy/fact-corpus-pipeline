"""Применение решений из dispositions.json к реестру.

`waive` → требование переводится в rejected (обязательство снято, причина остаётся в
dispositions.json). Остальные цели проверяются предикатом заново, доказательство
перевыпускается: после правки выводов решение должно обновляться без ручной возни.

Запуск: CORPUS_ROOT=/path/to/project python3 $SKILL/apply_dispositions.py
"""
import contextlib
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CORPUS_ROOT") or Path.cwd()).resolve()
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, os.environ.get("GRACE_REGISTRY", str(Path.home() / "projects" / "vector-grace" / "registry")))
import dispositions  # noqa: E402
from grace_registry import cli, model, replay  # noqa: E402

BY = "agent:claude-code/registry-0.1"
CHECKER = ROOT / "docs/registry/checkers/check_fact_in_conclusions.py"


def run(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = cli.main(["--root", str(ROOT), *argv])
    return code, buf.getvalue()


def main() -> int:
    decisions = dispositions.load(ROOT)
    if not decisions:
        print(f"нет решений: {ROOT / 'docs/registry/dispositions.json'} (сначала apply_fact_decisions.py)")
        return 0

    # Предикат живёт в двух файлах: v1 (история) и v2 (версия 4). Берём любой из них,
    # иначе требования, перевыпущенные под новый предикат, остаются «без инварианта».
    invariants: dict[str, str] = {}
    for record in model.load_jsonl(ROOT / "docs/registry/invariants.jsonl"):
        path = (record.get("predicate") or {}).get("path", "")
        if "check_fact_in_conclusions" not in path:
            continue
        current = invariants.get(record["req_id"])
        if current is None or record["inv_id"] > current:
            invariants[record["req_id"]] = record["inv_id"]

    waived = checked = 0
    for req_id, entry in sorted(decisions.items()):
        target = entry["target"]
        if target == "waive":
            code, out = run("revise", "--req", req_id, "--status", "rejected",
                            "--owner", entry.get("by") or "аналитик", "--by", BY)
            if code != 0:
                print(f"{req_id}: снять не удалось — {out.strip()[:120]}")
                continue
            waived += 1
            print(f"{req_id}: снято — {entry.get('reason', 'без причины')}")
            continue
        inv_id = invariants.get(req_id)
        if not inv_id:
            print(f"{req_id}: нет инварианта — пропуск")
            continue
        outcome = replay.run_checker(CHECKER, ROOT, req_id)
        code, out = run("evidence", "--req", req_id, "--inv", inv_id, "--transition", req_id,
                        "--result", "pass" if outcome["ok"] else "fail",
                        "--defeater", "если факт есть там, где решено его разместить",
                        "--detail", outcome["detail"][:220],
                        "--code-root", "docs/registry/checkers", "--by", BY)
        if code != 0:
            print(f"{req_id}: доказательство не записано — {out.strip()[:120]}")
            continue
        checked += 1
        print(f"{req_id} [{target}]: {'pass' if outcome['ok'] else 'fail'} — {outcome['detail'][:90]}")
    print(f"итого: снято {waived}, перепроверено {checked}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
