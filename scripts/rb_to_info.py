"""Правило «второстепенный рынок → справочно».

Колоды дают несколько панелей на одном слайде (`### РФ` / `### РБ`). Если цель бренда —
один рынок, обязательства, опирающиеся на строки другого, остаются фактами, но перестают
быть обязательствами выводов: они живут в приложении «Справочно» с причиной.

Связь требования и факта — по дословной строке таблицы: панель берётся из ближайшего
заголовка `###`, страница факта — из самого факта (а не None).

Запуск:
  CORPUS_ROOT=/path/to/project python3 $SKILL/rb_to_info.py --panel РБ
  … --apply          записать решения (без флага — только показать)
  … --reason "…"     причина в приложении
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402

DEFAULT_REASON = "второстепенный рынок: основная цель — другой рынок"


def deck_of(record: dict) -> str:
    """Имя колоды из источника требования; пусто, если требование не из decks/."""
    file = (record.get("source") or {}).get("file", "")
    parts = file.split("/")
    return parts[1] if len(parts) > 2 and parts[0] == "decks" else ""


def panel_index() -> dict[tuple[str, str], str]:
    """(колода, строка таблицы) → панель."""
    index: dict[tuple[str, str], str] = {}
    decks = corpus.ROOT / "decks"
    if not decks.is_dir():
        return index
    for path in sorted(decks.glob("*/*.md")):
        deck = path.parent.name
        for row in corpus.rows(deck):
            index[(deck, row["raw"])] = row["panel"]
    return index


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--panel", default="РБ", help="какая панель уходит в справочно")
    parser.add_argument("--reason", default=DEFAULT_REASON)
    args = parser.parse_args()

    config = corpus.load_config()
    panels = panel_index()
    latest = {}
    for record in corpus.load_jsonl(corpus.REQUIREMENTS):
        latest[record["req_id"]] = record

    decisions = json.loads(corpus.DECISIONS.read_text("utf-8")) if corpus.DECISIONS.is_file() else {}
    dispositions = json.loads(corpus.DISPOSITIONS.read_text("utf-8")) if corpus.DISPOSITIONS.is_file() else {}

    facts_by_deck: dict[str, list[dict]] = {}
    for fact in corpus.load_facts():
        facts_by_deck.setdefault(fact["deck"], []).append(fact)

    targets = []
    for req_id, record in sorted(latest.items()):
        if record.get("status") != "elicited":
            continue
        deck = deck_of(record)
        if not deck:
            continue
        if panels.get((deck, record["raw_text"].strip())) == args.panel:
            targets.append((req_id, record, deck))

    print(f"обязательств на панели «{args.panel}»: {len(targets)}")
    linked = skipped = 0
    for req_id, record, deck in targets:
        cells = [cell.strip() for cell in record["raw_text"].strip().strip("|").split("|")]
        label = cells[0] if cells else ""
        value = " / ".join(cells[1:]) if len(cells) > 1 else ""
        matched = []
        for fact in facts_by_deck.get(deck, []):
            row = corpus.row_for_fact(deck, fact.get("page"), fact["label"], fact["value"])
            if row is not None and row["raw"] == record["raw_text"].strip():
                matched.append(fact)
        fact = matched[0] if matched else None
        print(f"  {req_id}: стр.{fact['page'] if fact else '—'} — {label[:60]} = {value[:30]}")
        dispositions[req_id] = {"target": "info", "reason": args.reason, "by": config["decided_by"]}
        if not args.apply:
            continue
        if fact is None:
            skipped += 1
            print("     факт не найден — требование остаётся без решения по факту")
            continue
        decisions[fact["fact_id"]] = {
            "target": "info",
            "reason": args.reason,
            "deck": deck,
            "page": fact["page"],
            "label": fact["label"],
            "value": fact["value"],
            "req_id": req_id,
            "req_ids": [req_id],
        }
        linked += 1

    if not args.apply:
        print("пробный прогон: добавь --apply, чтобы записать")
        return 0

    corpus.write_json(corpus.DECISIONS, decisions)
    corpus.write_json(corpus.DISPOSITIONS, dispositions)
    print(f"записано: решений по фактам {len(decisions)} (связано {linked}, без факта {skipped}), "
          f"диспозиций {len(dispositions)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
