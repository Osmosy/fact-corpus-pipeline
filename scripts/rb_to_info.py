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


def material_fact_ids() -> set[str]:
    """Факты, признанные материалом: согласие в сравнении или вердикты слепых зон.

    Панель РБ означает, где измерено, а не является ли факт опорой выводов. Поэтому материал
    двух каналов правило рынка не переводит (решение владельца, REQ-0008).
    """
    found: set[str] = set()
    for path in sorted((corpus.ROOT / "docs/facts").glob("COMPARISON-*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))
        found.update(body.get("consensus") or [])
    review_path = corpus.ROOT / "docs/facts/BLIND-SPOTS-REVIEW.json"
    if review_path.is_file():
        review = json.loads(review_path.read_text(encoding="utf-8"))
        for channel in review.values():
            if not isinstance(channel, dict):
                continue
            for fact_id, verdict in (channel.get("verdicts") or {}).items():
                value = verdict.get("verdict") if isinstance(verdict, dict) else verdict
                if str(value) == "material":
                    found.add(fact_id)
    return found


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

    config = corpus.load_config(required=("decided_by",))
    panels = panel_index()
    latest = {}
    for record in corpus.load_jsonl(corpus.REQUIREMENTS):
        latest[record["req_id"]] = record

    decisions = json.loads(corpus.DECISIONS.read_text("utf-8")) if corpus.DECISIONS.is_file() else {}
    dispositions = json.loads(corpus.DISPOSITIONS.read_text("utf-8")) if corpus.DISPOSITIONS.is_file() else {}

    # индекс строится один раз за запуск: колода читается один раз, факт ищет свою строку
    # в готовом индексе, а не перечитывает markdown на каждое требование
    facts_by_raw: dict[tuple[str, str], list[dict]] = {}
    ambiguous: list[str] = []
    for fact in corpus.load_facts():
        row, reason = corpus.resolve_row(fact["deck"], fact.get("page"), fact["label"], fact["value"])
        if row is None:
            if reason and reason.startswith("неоднозначно"):
                ambiguous.append(f"{fact['fact_id']}: {reason} (стр. {fact['page']}, "
                                 f"{fact['label']} = {fact['value']})")
            continue
        facts_by_raw.setdefault((fact["deck"], row["raw"]), []).append(fact)

    targets = []
    for req_id, record in sorted(latest.items()):
        if record.get("status") != "elicited":
            continue
        deck = deck_of(record)
        if not deck:
            continue
        if panels.get((deck, record["raw_text"].strip())) == args.panel:
            targets.append((req_id, record, deck))

    # материал по двум каналам правило рынка не переводит: панель говорит, где измерено,
    # а не является ли факт опорой выводов (решение владельца 02.11.2026, REQ-0008)
    material_facts = material_fact_ids()
    kept = []
    if material_facts:
        remaining = []
        for req_id, record, deck in targets:
            matched = facts_by_raw.get((deck, record["raw_text"].strip()), [])
            fact = matched[0] if matched else None
            if fact and fact["fact_id"] in material_facts:
                kept.append((req_id, fact))
            else:
                remaining.append((req_id, record, deck))
        targets = remaining

    print(f"обязательств на панели «{args.panel}»: {len(targets)}")
    if kept:
        print(f"  оставлены в выводах, потому что факт — материал по вердиктам: {len(kept)}")
        for req_id, fact in kept:
            print(f"    {req_id}: {fact['label'][:50]} = {fact['value'][:20]} (стр.{fact['page']})")
    linked = skipped = 0
    for req_id, record, deck in targets:
        cells = [cell.strip() for cell in record["raw_text"].strip().strip("|").split("|")]
        label = cells[0] if cells else ""
        value = " / ".join(cells[1:]) if len(cells) > 1 else ""
        matched = facts_by_raw.get((deck, record["raw_text"].strip()), [])
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
    if ambiguous:
        print(f"нужно решение человека — {len(ambiguous)} факт(ов) с одинаковой подписью и "
              "значением в разных панелях:")
        for note in ambiguous:
            print("  ", note)
    print(f"записано: решений по фактам {len(decisions)} (связано {linked}, без факта {skipped}), "
          f"диспозиций {len(dispositions)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
