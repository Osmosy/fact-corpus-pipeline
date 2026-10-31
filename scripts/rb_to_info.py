"""Рынок РБ → справочно: правило заказчика (основная цель — рынок РФ).

Колоды дают две панели на одном слайде (### РФ / ### РБ). Обязательство, опирающееся на
строку белорусской панели, остаётся фактом, но перестаёт быть обязательством выводов:
оно живёт в приложении «Справочно» с причиной «рынок РБ, основная цель — РФ».

Запуск:
  python3 docs/facts/rb_to_info.py            — только показать, что попадёт под правило;
  python3 docs/facts/rb_to_info.py --apply    — записать решения.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CORPUS_ROOT") or Path.cwd()).resolve()
DECKS = ROOT / "decks"
REQUIREMENTS = ROOT / "docs/requirements-registry.jsonl"
DECISIONS = ROOT / "docs/facts/fact_decisions.json"
DISPOSITIONS = ROOT / "docs/registry/dispositions.json"
FACTS = ROOT / "docs/facts/facts.jsonl"
DEFAULT_REASON = "второстепенный рынок: основная цель — другой рынок"
BY = "заказчик 31.10.2026"


def panel_map() -> dict[str, str]:
    """строка таблицы → 'РФ' | 'РБ' | '' (панель не размечена)."""
    mapping: dict[str, str] = {}
    for deck_dir in sorted(DECKS.iterdir()):
        path = deck_dir / f"{deck_dir.name}.md"
        if not path.is_file():
            continue
        panel = ""
        for line in path.read_text("utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                panel = ""
                continue
            if stripped.startswith("### "):
                head = stripped[4:].strip().upper()
                panel = "РФ" if head.startswith("РФ") else "РБ" if head.startswith("РБ") else ""
                continue
            if stripped.startswith("|") and panel:
                mapping.setdefault(f"{deck_dir.name}|{stripped}", panel)
    return mapping


def latest_requirements() -> dict[str, dict]:
    latest = {}
    for line in REQUIREMENTS.read_text("utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            latest[record["req_id"]] = record
    return latest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--panel", default="РБ", help="какая панель уходит в справочно")
    parser.add_argument("--reason", default=DEFAULT_REASON)
    args = parser.parse_args()

    panels = panel_map()
    reqs = latest_requirements()
    facts = {}
    for line in FACTS.read_text("utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            facts[row["fact_id"]] = row

    targets = []
    for req_id, record in sorted(reqs.items()):
        if record.get("status") != "elicited":
            continue
        deck = record["source"]["file"].split("/")[1] if record["source"]["file"].startswith("decks/") else ""
        key = f"{deck}|{record['raw_text'].strip()}"
        if panels.get(key) == args.panel:
            targets.append((req_id, record))

    decisions = json.loads(DECISIONS.read_text("utf-8")) if DECISIONS.is_file() else {}
    dispositions = json.loads(DISPOSITIONS.read_text("utf-8")) if DISPOSITIONS.is_file() else {}

    print(f"обязательств на панели РБ: {len(targets)}")
    by_fact = {}
    for fid, row in facts.items():
        by_fact[(row["deck"], row["page"], row["label"], row["value"])] = fid

    for req_id, record in targets:
        cells = [c.strip() for c in record["raw_text"].strip().strip("|").split("|")]
        label = cells[0] if cells else ""
        value = " / ".join(cells[1:]) if len(cells) > 1 else ""
        print(f"  {req_id}: стр. — {label[:60]} = {value[:30]}")
        dispositions[req_id] = {"target": "info", "reason": args.reason, "by": BY}
        if args.apply:
            candidates = [
                fid for (deck, page, flabel, fvalue), fid in by_fact.items()
                if flabel[:40] == label[:40] and fvalue.rstrip(" %") in record["raw_text"]
            ]
            fid = candidates[0] if candidates else f"req:{req_id}"
            decisions[fid] = {
                "target": "info",
                "reason": args.reason,
                "deck": record["source"]["file"].split("/")[1],
                "page": None,
                "label": label,
                "value": value,
                "req_id": req_id,
            }

    if not args.apply:
        print("пробный прогон: добавь --apply, чтобы записать")
        return 0

    DECISIONS.write_text(json.dumps(decisions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    DISPOSITIONS.write_text(json.dumps(dispositions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"записано: решений по фактам {len(decisions)}, диспозиций {len(dispositions)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
