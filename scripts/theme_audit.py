#!/usr/bin/env python3
"""Аудит границы темы: нетематические факты, которые не взял никто.

Слепые зоны ищутся только среди тематических, поэтому нетематические не проверяются вовсе —
а граница темы (список основ) прямо меняет их состав. Здесь модель получает пакет таких
фактов и отвечает «тема / не тема» с причиной; спорные попадают в отчёт с предложением
основ.

В конфиг ничего не пишется автоматически: расширение `theme_stems` — решение человека.
Если основы добавлены, дальше `build_facts.py` → `blind_spots.py --diff` → документы.

Запуск:
  CORPUS_ROOT=/path/to/project python3 $SKILL/theme_audit.py --channel zcode --sample 40 --seed 7
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402
import matching  # noqa: E402
import run_analysis as ra  # noqa: E402

OUT = corpus.ROOT / "docs/facts/THEME-AUDIT.json"
OUT_MD = corpus.ROOT / "docs/facts/THEME-AUDIT.md"
TASK = """Ниже факты, которые конвейер счёл нетематическими (не про вопрос). Проверь каждый.
Верни ТОЛЬКО JSON такого вида:
{"verdicts": [{"fact_id": "F-…", "theme": "yes|no", "why": "до 12 слов", "stem": "основа"}]}
theme=yes — факт всё-таки про вопрос; theme=no — граница верна;
stem — короткая основа (3–6 букв), по которой такие факты ловились бы (только при yes).
fact_id бери дословно из списка, у каждого факта из списка должен быть вердикт."""


def candidates(thematic: bool = False) -> list[dict]:
    taken: set[str] = set()
    for deck in {row["deck"] for row in corpus.load_facts()}:
        for run in corpus.load_runs(deck):
            for item in run["body"]["answer"].get("selected", []):
                if isinstance(item, dict) and item.get("fact_id"):
                    taken.add(item["fact_id"])
    return [row for row in corpus.load_facts()
            if row["thematic"] is thematic and row["fact_id"] not in taken]


def audit(channel: str, sample: int | None, seed: int, model: str | None) -> int:
    rows = candidates()
    if sample and sample < len(rows):
        rows = random.Random(seed).sample(rows, sample)
    if not rows:
        print("нет нетематических невзятых фактов")
        return 2
    config = corpus.load_config(required=("question", "role"))
    base = f"Ты {config['role']}. {TASK}\n\n{config['question']}\n\nФакты:\n"
    base += "\n".join(f"{row['fact_id']} | стр.{row['page']} | {row['label']} | {row['value']}"
                      for row in rows)
    print(f"{channel}: {len(rows)} фактов, промпт {len(base)} символов")
    started = time.time()
    try:
        answer, meta = ra.call(channel, base, keys=("verdicts", "facts"), model=model or None)
    except Exception as error:  # noqa: BLE001
        print(f"канал упал: {type(error).__name__}: {error}")
        return 1
    try:
        body = json.loads(answer) if answer else {}
    except json.JSONDecodeError as error:
        print(f"ответ не разбирается: {error}")
        return 1

    items = None
    if isinstance(body, dict):
        items = body.get("verdicts") or body.get("facts") or body.get("items")
    elif isinstance(body, list):
        items = body
    if not isinstance(items, list):
        print("в ответе нет списка verdicts")
        return 1
    by_id = {row["fact_id"]: row for row in rows}
    yes, no, stems = [], [], []
    for item in items:
        if not isinstance(item, dict) or item.get("fact_id") not in by_id:
            continue
        row = by_id[item["fact_id"]]
        theme = str(item.get("theme") or "").lower() in ("yes", "да", "true")
        entry = {"fact_id": row["fact_id"], "deck": row["deck"], "page": row["page"],
                 "label": row["label"], "value": row["value"],
                 "why": str(item.get("why") or "")[:200], "stem": item.get("stem")}
        (yes if theme else no).append(entry)
        if theme and item.get("stem"):
            stems.append(str(item["stem"])[:12])

    payload = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "channel": channel,
               "sample": len(rows), "seed": seed, "answered": len(yes) + len(no),
               "thematic": len(yes), "not_thematic": len(no),
               "share_mistaken": round(len(yes) / max(1, len(yes) + len(no)), 3),
               "usage": corpus.normalize_usage((meta or {}).get("usage")),
               "seconds": round(time.time() - started, 1),
               "suggested_stems": sorted({stem.lower() for stem in stems if len(stem) >= 3}),
               "facts": yes}
    corpus.write_json(OUT, payload)
    lines = [f"# Аудит темы ({channel})", "",
             f"выборка {len(rows)} фактов, ответили {payload['answered']}, "
             f"оказались про тему {len(yes)} ({payload['share_mistaken']:.0%})", "",
             "| факт | страница | подпись | значение | предполагаемая основа |",
             "|---|---|---|---|---|"]
    for entry in yes:
        lines.append(f"| {entry['fact_id']} | {entry['page']} | {entry['label']} | "
                     f"{entry['value']} | `{entry.get('stem') or ''}` |")
    if payload["suggested_stems"]:
        lines += ["", "Предложение в `theme_stems` (решение за человеком): "
                      + ", ".join(f"`{stem}`" for stem in payload["suggested_stems"])]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"про тему {len(yes)} из {payload['answered']} ({payload['share_mistaken']:.0%}) → "
          f"{corpus.rel(OUT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="zcode")
    parser.add_argument("--sample", type=int, default=None)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()
    return audit(args.channel, args.sample, args.seed, args.model)


if __name__ == "__main__":
    sys.exit(main())
