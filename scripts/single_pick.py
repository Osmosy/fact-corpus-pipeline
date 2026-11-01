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

OUT = corpus.ROOT / "docs/facts/SINGLE-REVIEW.json"          # слияние по корпусу
OUT_MD = corpus.ROOT / "docs/facts/SINGLE-REVIEW.md"
OUT_IDS = corpus.ROOT / "docs/facts/SINGLE-IDS.json"


def single_facts(deck: str, not_by: str | None = None) -> list[dict]:
    """Факты «выбрал ровно один»; `not_by` — оставить те, что этот канал не выбирал.

    Оценивать факт должна та модель, которая его не взяла: иначе это самооценка.
    """
    path = corpus.ROOT / f"docs/facts/COMPARISON-{deck}.json"
    if not path.is_file():
        return []
    body = json.loads(path.read_text("utf-8"))
    facts = {row["fact_id"]: row for row in corpus.load_facts(deck)}
    picked = picked_by_channel(deck)
    out = []
    for item in body.get("single") or []:
        fact_id = item if isinstance(item, str) else item.get("fact_id")
        if not fact_id or fact_id not in facts:
            continue
        channels = picked.get(fact_id, [])
        if not_by and not_by in channels:
            continue                      # канал сам выбрал факт — это была бы самооценка
        out.append({**facts[fact_id], "picked_by": ",".join(channels)})
    return out


def picked_by_channel(deck: str) -> dict[str, list[str]]:
    """Какие каналы выбирали факт — по тем прогонам, что вошли в сравнение.

    Повторы пилота складывать нельзя: факт, выбранный в одном повторе из трёх, формально
    «выбран обоими каналами», и оба канала от него отказываются — факт выпадает из разбора.
    Поэтому берётся последний принятый прогон на канал, как и в compare_analyses.
    """
    last: dict[str, dict] = {}
    for run in corpus.load_runs(deck):
        body = run.get("body", run)
        backend = body["backend"]
        if backend not in last or run.get("stamp", "") >= last[backend].get("stamp", ""):
            last[backend] = run
    out: dict[str, list[str]] = {}
    for backend, run in last.items():
        body = run.get("body", run)
        for item in (body.get("answer") or {}).get("selected", []):
            if isinstance(item, dict) and item.get("fact_id"):
                channels = out.setdefault(item["fact_id"], [])
                if backend not in channels:
                    channels.append(backend)
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
    rows = single_facts(deck, not_by=channel)
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
    part = corpus.ROOT / f"docs/facts/SINGLE-REVIEW-{deck}-{channel}.json"
    corpus.write_json(part, payload)
    lines = [f"# Факты «выбрал один»: {deck}", "",
             f"канал {channel}, фактов {len(rows)}, материал {payload['groups']['all_material']}, "
             f"фон {payload['groups']['all_background']}"]
    for fact_id, row in sorted(ids.items(), key=lambda kv: (kv[1]["verdict"] or "")):
        lines.append(f"- {fact_id} стр.{row['page']} | {row['label']} = {row['value']} → "
                     f"{row['verdict']} ({row['why'][:80]})")
    part_md = corpus.ROOT / f"docs/facts/SINGLE-REVIEW-{deck}-{channel}.md"
    part_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for problem in problems:
        print("  проблема:", problem)
    print(f"материал {payload['groups']['all_material']}, фон {payload['groups']['all_background']} → "
          f"{corpus.rel(part)}")
    return 0 if not problems else 1


def merge() -> int:
    """Свести разборы по колодам и каналам в один файл корпуса."""
    parts = sorted(corpus.ROOT.glob("docs/facts/SINGLE-REVIEW-*.json"))
    # в слияние идут только факты, которые «выбрал один» в текущем сравнении: после
    # отделения прогонов шума часть прежних частей устарела
    current: set[str] = set()
    for path in corpus.ROOT.glob("docs/facts/COMPARISON-*.json"):
        for item in json.loads(path.read_text("utf-8")).get("single") or []:
            current.add(item if isinstance(item, str) else item.get("fact_id"))
    if not parts:
        print("нет частей SINGLE-REVIEW-<колода>-<канал>.json")
        return 2
    ids: dict[str, dict] = {}
    groups = {"all_material": 0, "split": 0, "all_background": 0, "not_all_answered": 0}
    seen: dict[str, dict] = {}
    for path in parts:
        body = json.loads(path.read_text("utf-8"))
        for name, count in (body.get("groups") or {}).items():
            groups[name] = groups.get(name, 0) + count
        for fact_id, row in (body.get("ids") or {}).items():
            if fact_id in seen or (current and fact_id not in current):
                continue
            seen[fact_id] = row
            ids[fact_id] = {"label": row["label"], "value": row["value"], "page": row["page"],
                            "deck": row["deck"], "verdict": row.get("verdict"),
                            "repeat_picks": row.get("repeat_picks"),
                            "reviewed_by": body["channel"]}
    payload = {"total": len(ids), "parts": len(parts), "groups": groups, "ids": ids,
               "material": sum(1 for row in ids.values() if row.get("verdict") == "material")}
    corpus.write_json(OUT, payload)
    corpus.write_json(OUT_IDS, {"total": len(ids),
                                "ids": {fact_id: {"label": row["label"], "value": row["value"]}
                                        for fact_id, row in ids.items()}})
    lines = ["# Факты «выбрал один»: разбор", "",
             f"всего {len(ids)} (частей {len(parts)}): материал {groups.get('all_material', 0)}, "
             f"фон {groups.get('all_background', 0)}, спорные {groups.get('split', 0)}, "
             f"ответили не все {groups.get('not_all_answered', 0)}", "",
             "| факт | колода | стр. | подпись | значение | вердикт | повторов |",
             "|---|---|---|---|---|---|---|"]
    for fact_id, row in sorted(ids.items(), key=lambda kv: str(kv[1].get("verdict"))):
        lines.append(f"| {fact_id} | {row['deck']} | {row['page']} | {row['label']} | "
                     f"{row['value']} | {row.get('verdict')} | {row.get('repeat_picks')} |")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"слито {len(ids)} фактов из {len(parts)} частей: материал {groups.get('all_material', 0)}, "
          f"фон {groups.get('all_background', 0)} → {corpus.rel(OUT)}")
    return 0


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
    parser.add_argument("--merge", action="store_true")
    args = parser.parse_args()
    if args.diff:
        return diff()
    if args.merge:
        return merge()
    if not (args.deck and args.channel):
        print("нужны --deck и --channel")
        return 2
    return review(args.deck, args.channel, args.model)


if __name__ == "__main__":
    sys.exit(main())
