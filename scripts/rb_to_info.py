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


MARKER_HINTS = ("пометк", "маркер", "с пометкой", "только с")


def normalize_marker(value, aliases: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    """Значение `require_marker` → список названий панелей; вторым — неизвестные значения.

    Пишут по-разному: `"РБ"`, `"🇧🇾"`, `["РБ", "РФ"]`. Панель приводится к каноническому
    названию через `panel_aliases`, чтобы чекер и это правило говорили на одном языке.
    """
    if value is None or value == "":
        return [], []
    raw = value if isinstance(value, list) else [value]
    known: list[str] = []
    unknown: list[str] = []
    for item in raw:
        text = str(item).strip()
        if not text:
            continue
        if text in aliases:
            if text not in known:
                known.append(text)
            continue
        match = next((panel for panel, words in aliases.items()
                      if any(str(word).strip() == text for word in words or [])), "")
        if match:
            if match not in known:
                known.append(match)
        elif text not in unknown:
            unknown.append(text)
    return known, unknown


def owner_exceptions() -> dict[str, dict]:
    """Явные исключения владельца из правила рынка: только данными, не правилом в коде.

    Формат `config.json → owner_exceptions`: [{"req_id": "REQ-00NN", "reason": "...",
    "date": "ГГГГ-ММ-ДД", "signed_by": "кто", "require_marker": "РБ"}]. Пустой список —
    нормальное состояние: правило действует без исключений. Исключение без причины, даты
    и подписи не принимается.

    `require_marker` — структурный признак: какие панели обязаны быть помечены в выводах.
    Условие, записанное словами в причине, проверяться не будет, поэтому про него отдельное
    предупреждение. В записи остаётся приведённое значение (`marker`), чтобы чекер не
    разбирал текст и не зависел от формулировки.
    """
    try:
        config = corpus.load_config(required=()) or {}
    except SystemExit:
        return {}
    aliases = config.get("panel_aliases") or {}
    configured = config.get("owner_exceptions") or []
    found: dict[str, dict] = {}
    for entry in configured:
        if not isinstance(entry, dict) or not entry.get("req_id"):
            continue
        req_id = str(entry["req_id"])
        if not (entry.get("reason") and entry.get("date") and entry.get("signed_by")):
            print(f"  исключение {req_id} пропущено: нет причины, даты или подписи",
                  file=sys.stderr)
            continue
        marker, unknown = normalize_marker(entry.get("require_marker"), aliases)
        for value in unknown:
            print(f"  исключение {req_id}: панель «{value}» в require_marker не найдена "
                  f"в panel_aliases — маркер не проверяется", file=sys.stderr)
        reason = str(entry.get("reason") or "").lower()
        if not marker and any(hint in reason for hint in MARKER_HINTS):
            print(f"  исключение {req_id}: условие записано словами в причине, но поля "
                  f"require_marker нет — маркер панели проверяться не будет",
                  file=sys.stderr)
        record = dict(entry)
        record["marker"] = marker
        found[req_id] = record
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
        panel = panels.get((deck, record["raw_text"].strip()))
        if panel and panel == args.panel:
            targets.append((req_id, record, deck))

    on_panel_total = sum(1 for record in latest.values()
                         if deck_of(record)
                         and panels.get((deck_of(record), record["raw_text"].strip())) == args.panel)

    exceptions = owner_exceptions()
    kept = [(req_id, exceptions[req_id]) for req_id, _record, _deck in targets
            if req_id in exceptions]
    if kept:
        targets = [item for item in targets if item[0] not in exceptions]

    print(f"панель «{args.panel}»: {on_panel_total}, из них в «Справочно» {len(targets)}, "
          f"исключения владельца {len(kept)}")
    if kept:
        # исключение владельца — не «оставить как есть», а осознанная судьба: требование
        # закрывается выводами, но число в них обязано идти с пометкой панели
        print(f"  исключения владельца → conclusions: {len(kept)}")
        for req_id, entry in kept:
            marker = ", ".join(entry.get("marker") or []) or "нет — число без пометки панели"
            print(f"    {req_id}: маркер «{marker}» — {entry.get('reason')} "
                  f"({entry.get('date')}, {entry.get('signed_by')})")
            dispositions[req_id] = {"target": "conclusions", "reason": entry.get("reason"),
                                    "by": entry.get("signed_by") or config["decided_by"]}
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
            print("     факт не найден — требование остаётся без решения по факту",
              file=sys.stderr)
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
              "значением в разных панелях:", file=sys.stderr)
        for note in ambiguous:
            print("  ", note, file=sys.stderr)
    print(f"записано: решений по фактам {len(decisions)} (связано {linked}, без факта {skipped}), "
          f"диспозиций {len(dispositions)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
