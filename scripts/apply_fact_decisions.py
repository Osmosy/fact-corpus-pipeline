"""Применяет решения по фактам: справочно / в выводы.

Пишет три вещи:
  docs/facts/fact_decisions.json      — решение по каждому факту с причиной;
  reviews/.../APPENDIX-INFO.md        — приложение «Справочно» (туда смотрит предикат для info);
  docs/registry/dispositions.json     — решения по требованиям (для apply_dispositions.py).

Решение по факту и решение по требованию — разные слои: факт может быть справочным, не
становясь требованием вовсе.
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CORPUS_ROOT") or Path.cwd()).resolve()
FACTS = ROOT / "docs/facts/facts.jsonl"
DECISIONS = ROOT / "docs/facts/fact_decisions.json"
def appendix_path() -> Path:
    """Где приложение «Справочно»: APPENDIX_INFO, иначе единственное reviews/*/APPENDIX-INFO.md."""
    env = os.environ.get("APPENDIX_INFO")
    if env:
        return ROOT / env
    found = sorted((ROOT / "reviews").glob("*/APPENDIX-INFO.md"))
    return found[0] if found else ROOT / "reviews/APPENDIX-INFO.md"


APPENDIX = None  # вычисляется в main() через appendix_path()
DISPOSITIONS = ROOT / "docs/registry/dispositions.json"
REQUIREMENTS = ROOT / "docs/requirements-registry.jsonl"
BY = "заказчик 31.10.2026"

PLAN_FILE = ROOT / "docs/facts/plan.json"


def load_plan() -> dict[str, tuple[str, str]]:
    """План решений — данные проекта: {fact_id: [target, reason]}.

    Держать его в скрипте нельзя: решения меняются по ходу разбора, а скрипт должен
    оставаться одинаковым для всех корпусов.
    """
    if not PLAN_FILE.is_file():
        raise SystemExit(f"нет файла плана: {PLAN_FILE}")
    raw = json.loads(PLAN_FILE.read_text("utf-8"))
    return {fact_id: (entry[0], entry[1]) for fact_id, entry in raw.items()}


def load_facts() -> dict[str, dict]:
    rows = {}
    for line in FACTS.read_text("utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[row["fact_id"]] = row
    return rows


def requirements_by_text() -> dict[str, list[str]]:
    """raw_text требования → все req_id с таким текстом (одна строка может нести несколько)."""
    latest = {}
    for line in REQUIREMENTS.read_text("utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            latest[record["req_id"]] = record
    mapping: dict[str, list[str]] = {}
    for rid, record in latest.items():
        mapping.setdefault(record["raw_text"].strip(), []).append(rid)
    return mapping


def row_text(deck: str, label: str, value: str) -> str:
    """Дословная строка таблицы колоды, в которой стоит факт."""
    path = ROOT / f"decks/{deck}/{deck}.md"
    text = path.read_text("utf-8")
    wanted_label = label.strip()
    wanted_value = value.strip()
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        if wanted_label[:40] in line and wanted_value.rstrip(" %") in line:
            return line.strip()
    return ""


def main() -> int:
    facts = load_facts()
    reqs = requirements_by_text()
    decisions: dict[str, dict] = json.loads(DECISIONS.read_text("utf-8")) if DECISIONS.is_file() else {}
    dispositions: dict[str, dict] = (json.loads(DISPOSITIONS.read_text("utf-8"))
                                     if DISPOSITIONS.is_file() else {})
    missing = []

    for fid, (target, reason) in load_plan().items():
        fact = facts.get(fid)
        if not fact:
            missing.append(f"{fid}: нет в каноне")
            continue
        text = row_text(fact["deck"], fact["label"], fact["value"])
        req_ids = reqs.get(text, []) if text else []
        req_id = req_ids[0] if req_ids else None
        decisions[fid] = {
            "target": target,
            "reason": reason,
            "deck": fact["deck"],
            "page": fact["page"],
            "label": fact["label"],
            "value": fact["value"],
            "req_id": req_id,
        }
        if req_ids:
            for rid in req_ids:
                dispositions[rid] = {"target": target, "reason": reason, "by": BY}
        else:
            missing.append(f"{fid}: требования нет (факт остаётся только фактом)")

    DECISIONS.write_text(json.dumps(decisions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    DISPOSITIONS.write_text(json.dumps(dispositions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    info_rows = [(fid, d) for fid, d in decisions.items() if d["target"] == "info"]
    print(f"решений по фактам: {len(decisions)} (справочно {len(info_rows)}, "
          f"в выводы {len(decisions) - len(info_rows)}); требований затронуто: {len(dispositions)}")
    for note in missing:
        print("  ", note)
    print(f"→ {DECISIONS.relative_to(ROOT)}, {DISPOSITIONS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
