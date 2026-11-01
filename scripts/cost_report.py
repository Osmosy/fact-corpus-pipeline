#!/usr/bin/env python3
"""Расход по корпусу: сколько токенов и единиц пула съели прогоны и разбор вердиктов.

Читает docs/facts/runs/*.json (поле `usage`, `seconds`) и BLIND-SPOTS-REVIEW.json (там лежат
те же поля в `meta`), группирует по колоде и каналу. Ничего не запускает и не тратит.

Запуск: CORPUS_ROOT=/path/to/project python3 $SKILL/cost_report.py [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402

OUT = corpus.ROOT / "docs/facts/COST.json"


def add(bucket: dict, backend: str, usage: dict, seconds: float | None) -> None:
    row = bucket.setdefault(backend, {"runs": 0, "input_tokens": 0, "output_tokens": 0,
                                      "pool_units": 0, "seconds": 0.0, "runs_no_usage": 0})
    row["runs"] += 1
    row["seconds"] = round(row["seconds"] + float(seconds or 0), 1)
    known = False
    for field in ("input_tokens", "output_tokens", "pool_units"):
        value = (usage or {}).get(field)
        if isinstance(value, int):
            row[field] += value
            known = True
    if not known:
        row["runs_no_usage"] += 1


def collect() -> dict:
    by_deck: dict[str, dict] = {}
    if corpus.RUNS.is_dir():
        for path in sorted(corpus.RUNS.glob("*.json")):
            body = json.loads(path.read_text("utf-8"))
            deck = body.get("deck") or path.name.split(".")[0]
            backend = body.get("backend") or "unknown"
            usage = body.get("usage") or corpus.normalize_usage((body.get("meta") or {}).get("usage"))
            add(by_deck.setdefault(body.get("deck") or deck, {}), backend, usage, body.get("seconds"))

    review_path = corpus.ROOT / "docs/facts/BLIND-SPOTS-REVIEW.json"
    if review_path.is_file():
        review = json.loads(review_path.read_text("utf-8"))
        for backend, body in review.items():
            usage = corpus.normalize_usage((body.get("meta") or {}).get("usage"))
            add(by_deck.setdefault("(разбор слепых зон)", {}), backend, usage,
                (body.get("meta") or {}).get("seconds"))

    totals: dict[str, dict] = {}
    for channels in by_deck.values():
        for backend, row in channels.items():
            add(totals, backend, {field: row[field] for field in
                                  ("input_tokens", "output_tokens", "pool_units")}, row["seconds"])
    return {"decks": by_deck, "totals": totals}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = collect()
    corpus.write_json(OUT, report)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    for deck, channels in sorted(report["decks"].items()):
        print(deck)
        for backend, row in sorted(channels.items()):
            print(f"  {backend:12s} прогонов {row['runs']:2d} | вход {row['input_tokens']:>9} | "
                  f"выход {row['output_tokens']:>7} | пул {row['pool_units']:>10} | "
                  f"{row['seconds']:>7.1f} с"
                  + (f" | без usage: {row['runs_no_usage']}" if row["runs_no_usage"] else ""))
    print("итого по каналам:")
    for backend, row in sorted(report["totals"].items()):
        print(f"  {backend:12s} прогонов {row['runs']:2d} | пул {row['pool_units']:>10} | "
              f"{row['seconds']:>7.1f} с")
    print(f"→ {corpus.rel(OUT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
