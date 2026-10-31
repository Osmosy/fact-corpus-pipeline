"""Применяет план решений по фактам: справочно / в выводы / снять.

Пишет два файла:
  docs/facts/fact_decisions.json    — решение по каждому факту с причиной и координатами;
  docs/registry/dispositions.json   — те же решения в терминах требований.

Само приложение «Справочно» пишет build_appendix.py — единственный генератор, чтобы два
скрипта не давали две версии документа.

План лежит в docs/facts/plan.json (данные проекта, а не константа скрипта):
  {"F-…": ["info", "почему так решили"], "F-…": ["conclusions", "…"]}

Связь факта с требованием — по дословной строке таблицы: строка ищется на странице факта,
значение сравнивается целой ячейкой, поэтому панели РФ/РБ не путаются.

Запуск: CORPUS_ROOT=/path/to/project python3 $SKILL/apply_fact_decisions.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402


def load_plan() -> dict[str, tuple[str, str]]:
    if not corpus.PLAN.is_file():
        raise SystemExit(
            f"нет плана решений: {corpus.PLAN}\n"
            "формат: {\"F-…\": [\"conclusions|info|waive\", \"причина\"]}; "
            "образец — scripts/examples/plan.example.json"
        )
    raw = json.loads(corpus.PLAN.read_text("utf-8"))
    plan: dict[str, tuple[str, str]] = {}
    for fact_id, entry in raw.items():
        if not isinstance(entry, list) or len(entry) < 2:
            raise SystemExit(f"{fact_id}: ожидается [target, причина], получено {entry!r}")
        target, reason = entry[0], entry[1]
        if target not in corpus.TARGETS:
            raise SystemExit(f"{fact_id}: target {target!r} вне {corpus.TARGETS}")
        plan[fact_id] = (target, str(reason))
    return plan


def requirements_by_text() -> dict[str, list[str]]:
    """raw_text требования → все req_id с этим текстом (одна строка может нести несколько)."""
    latest = {}
    for record in corpus.load_jsonl(corpus.REQUIREMENTS):
        latest[record["req_id"]] = record
    mapping: dict[str, list[str]] = {}
    for rid, record in latest.items():
        mapping.setdefault(record["raw_text"].strip(), []).append(rid)
    return mapping


def main() -> int:
    decided_by = corpus.load_config(required=("decided_by",))["decided_by"]
    facts = {row["fact_id"]: row for row in corpus.load_facts()}
    reqs = requirements_by_text()
    decisions: dict[str, dict] = (json.loads(corpus.DECISIONS.read_text("utf-8"))
                                  if corpus.DECISIONS.is_file() else {})
    dispositions: dict[str, dict] = (json.loads(corpus.DISPOSITIONS.read_text("utf-8"))
                                     if corpus.DISPOSITIONS.is_file() else {})
    missing, no_row, ambiguous = [], [], []

    for fact_id, (target, reason) in load_plan().items():
        fact = facts.get(fact_id)
        if not fact:
            missing.append(f"{fact_id}: нет в каноне фактов")
            continue
        row, why = corpus.resolve_row(fact["deck"], fact.get("page"), fact["label"], fact["value"])
        if row is None:
            if why and why.startswith("неоднозначно"):
                ambiguous.append(f"{fact_id}: {why} (стр. {fact.get('page')}, "
                                 f"{fact['label']} = {fact['value']})")
            else:
                no_row.append(f"{fact_id}: строка не найдена на стр. {fact.get('page')} "
                              f"колоды {fact['deck']} — требование не связано")
            req_ids: list[str] = []
        else:
            req_ids = reqs.get(row["raw"], [])

        decisions[fact_id] = {
            "target": target,
            "reason": reason,
            "deck": fact["deck"],
            "page": fact["page"],
            "label": fact["label"],
            "value": fact["value"],
            "req_id": req_ids[0] if req_ids else None,
            "req_ids": req_ids,
        }
        for rid in req_ids:
            dispositions[rid] = {"target": target, "reason": reason, "by": decided_by}
        if not req_ids:
            missing.append(f"{fact_id}: требования нет (факт остаётся только фактом)")

    corpus.write_json(corpus.DECISIONS, decisions)
    corpus.write_json(corpus.DISPOSITIONS, dispositions)

    info_rows = [fid for fid, decision in decisions.items() if decision["target"] == "info"]
    print(f"решений по фактам: {len(decisions)} (справочно {len(info_rows)}, "
          f"в выводы {len(decisions) - len(info_rows)}); требований затронуто: {len(dispositions)}")
    for note in no_row + missing:
        print("  ", note)
    if ambiguous:
        print(f"нужно решение человека — {len(ambiguous)} факт(ов) с одинаковой подписью и значением "
              "в разных панелях:")
        for note in ambiguous:
            print("  ", note)
    print(f"→ {corpus.rel(corpus.DECISIONS)}, {corpus.rel(corpus.DISPOSITIONS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
