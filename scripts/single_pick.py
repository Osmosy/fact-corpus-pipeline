#!/usr/bin/env python3
"""Разбор фактов «выбрал один»: их оценивает модель, которая их не выбрала.

Зачем: 105 фактов в кейсе выбрала ровно одна модель, и неизвестно, находка это или шум.
Механизм тот же, что у слепых зон: вердикт `material/background/irrelevant` от канала,
который факт не взял. Если модель, не выбиравшая факт, называет его материалом — это сигнал
пропуска, а не случайность.

Метка устойчивости: если для канала есть повторы (`STABILITY-*.json`), считается, сколько раз
факт выбирала та же модель; `--min-repeat 2` — порог «сигнал, а не шум» (по умолчанию 2).

Выход: `docs/facts/SINGLE-REVIEW.json` (+ снимок id) и `.md`.
  CORPUS_ROOT=/path/to/project python3 $SKILL/single_pick.py --channel zcode
  CORPUS_ROOT=/path/to/project python3 $SKILL/single_pick.py --diff
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402
import run_analysis as ra  # noqa: E402
import verdicts  # noqa: E402

OUT = corpus.ROOT / "docs/facts/SINGLE-REVIEW.json"
OUT_MD = corpus.ROOT / "docs/facts/SINGLE-REVIEW.md"
OUT_IDS = corpus.ROOT / "docs/facts/SINGLE-IDS.json"


def single_facts(deck: str) -> list[dict]:
    """Факты «выбрал ровно один» из сравнения: id и канал, который их взял."""
    path = corpus.ROOT / f"docs/facts/COMPARISON-{deck}.json"
    if not path.is_file():
        return []
    body = json.loads(path.read_text("utf-8"))
    facts = {row["fact_id"]: row for row in corpus.load_facts(deck)}
    out = []
    for item in body.get("single") or []:
        fact_id = item.get("fact_id")
        if fact_id in facts:
            out.append({**facts[fact_id], "picked_by": item.get("backend") or item.get("by")})
    return out


def repeat_counts(deck: str) -> dict[str, dict[str, int]]:
    """Сколько раз факт выбирал каждый канал в повторах (для метки устойчивости)."""
    counts: dict[str, dict[str, int]] = {}
    for path in sorted(corpus.RUNS.glob(f"{deck}.*.json")):
        body = json.loads(path.read_text("utf-8"))
        if not body.get("answer") or body.get("problems"):
            continue
        channel = body.get("backend")
        for item in body["answer"].get("selected", []):
            if isinstance(item, dict) and item.get("fact_id"):
                counts.setdefault(item["fact_id"], {})
                counts[item["fact_id"]][channel] = counts[item["fact_id"]].get(channel, 0) + 1
    return counts


def review(deck: str, channel: str, model: str | None) -> int:
    rows = single_facts(deck)
    if not rows:
        print(f"нет фактов «выбрал один» для {deck} — сначала compare_analyses.py")
        return 2
    config = corpus.load_config(required=("question", "role"))
    prompt = verdicts.build_prompt(
        deck, rows, config,
        "Ниже факты, каждый из которых выбрала только одна модель из нескольких. "
        "Оцени, нужны ли они для ответа на вопрос.")
    print(f"{channel}: {len(rows)} фактов «выбрал один», промпт {len(prompt)} символов")
    started = time.time()
    try:
        answer, meta = ra.call(channel, prompt, keys=("verdicts",), model=model or None)
    except Exception as error:  # noqa: BLE001 — сбой канала не должен терять разбора
        print(f"канал упал: {type(error).__name__}: {error}")
        return 1
    parsed, problems = verdicts.parse(answer)
    repeats = repeat_counts(deck)
    ids = {row["fact_id"]: {**row, "verdict": (parsed.get(row["fact_id"]) or {}).get("verdict"),
                            "why": (parsed.get(row["fact_id"]) or {}).get("why", ""),
                            "repeat_picks": repeats.get(row["fact_id"], {}).get(channel, 0)}
           for row in rows}
    groups = verdicts.summary({channel: parsed}, [row["fact_id"] for row in rows])
    payload = {"deck": deck, "channel": channel, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "seconds": round(time.time() - started, 1),
               "usage": corpus.normalize_usage((meta or {}).get("usage")),
               "problems": problems, "groups": {name: len(items) for name, items in groups.items()},
               "ids": ids}
    corpus.write_json(OUT, payload)
    corpus.write_json(OUT_IDS, {"deck": deck, "channel": channel,
                                "ids": {fact_id: {"label": row["label"], "value": row["value"],
                                                  "verdict": row["verdict"]}
                                        for fact_id, row in ids.items()}})
    lines = [f"# Факты «выбрал один»: {deck}", "",
             f"канал {channel}, фактов {len(rows)}, материал {payload['groups']['all_material']}, "
             f"фон {payload['groups']['all_background']}"]
    for fact_id, row in sorted(ids.items(), key=lambda kv: (kv[1]["verdict"] or "")):
        lines.append(f"- {fact_id} стр.{row['page']} | {row['label']} = {row['value']} → "
                     f"{row['verdict']} ({row['why'][:80]})")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for problem in problems:
        print("  проблема:", problem)
    print(f"материал {payload['groups']['all_material']}, фон {payload['groups']['all_background']} → "
          f"{corpus.rel(OUT)}")
    return 0 if not problems else 1


def diff() -> int:
    if not OUT_IDS.is_file():
        print(f"нет снимка {corpus.rel(OUT_IDS)} — сначала разбор без флагов")
        return 2
    before = json.loads(OUT_IDS.read_text("utf-8"))
    deck = before.get("deck")
    current = {row["fact_id"]: row for row in single_facts(deck)}
    gone = sorted(set(before.get("ids") or {}) - set(current))
    came = sorted(set(current) - set(before.get("ids") or {}))
    print(f"{deck}: было {len(before.get('ids') or {})} → стало {len(current)}: "
          f"ушли {len(gone)}, пришли {len(came)}")
    for fact_id in gone:
        print(f"  ушёл {fact_id} {before['ids'][fact_id].get('label')}")
    for fact_id in came:
        print(f"  пришёл {fact_id} стр.{current[fact_id]['page']} {current[fact_id]['label']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deck")
    parser.add_argument("--channel", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--diff", action="store_true")
    args = parser.parse_args()
    if args.diff:
        return diff()
    if not (args.deck and args.channel):
        print("нужны --deck и --channel")
        return 2
    return review(args.deck, args.channel, args.model)


if __name__ == "__main__":
    sys.exit(main())
