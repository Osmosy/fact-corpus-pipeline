#!/usr/bin/env python3
"""Шум прогонов: насколько выбор фактов устойчив внутри одного канала.

Тезис «массовый прогон теряет факты на внимании» проверяется так: одна и та же модель
прогоняется несколько раз с разным порядком фактов в промпте, и считается
  - попарный Жаккар выбранных множеств (среднее и минимум);
  - доля фактов, выбранных всеми повторами, частью и ни одним;
  - связь «не выбран» с позицией факта в промпте: доля невыбранных по децилям и
    перестановочный тест (насколько такое распределение вероятно случайно);
  - для фактов «выбрал один» из основного сравнения — сколько раз их выбирала та же модель.

Позиция берётся из прогона: `order` (перемешанный порядок, если был `--shuffle`) или порядок
канона. Повторы — файлы `<колода>.<канал>-<штамп>.json` одного канала.

Запуск: CORPUS_ROOT=/path/to/project python3 $SKILL/stability.py <колода> [--channel ИМЯ]
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402


def runs_of(deck: str, channel: str | None) -> list[dict]:
    """Повторы колоды. Если есть прогоны назначения `stability`, берутся только они.

    Базовый прогон шёл без перемешивания и с другим seed — для замера шума он лишний
    свидетель, но если повторов нет, годится и он.
    """
    out = []
    for path in sorted(corpus.RUNS.glob(f"{deck}.*.json")):
        body = json.loads(path.read_text("utf-8"))
        if not body.get("answer") or body.get("problems"):
            continue
        if channel and body.get("backend") != channel:
            continue
        selected = {item.get("fact_id") for item in body["answer"].get("selected", [])
                    if isinstance(item, dict)}
        out.append({"path": path.name, "backend": body.get("backend"),
                    "stamp": path.stem.split("-", 1)[-1], "selected": selected,
                    "order": body.get("order") or {},
                    "purpose": corpus.run_purpose(body)})
    repeats = [item for item in out if item["purpose"] == "stability"]
    return repeats if len(repeats) >= 2 else out


def jaccard(left: set, right: set) -> float:
    if not left and not right:
        return 1.0
    return len(left & right) / len(left | right)


def decile_effect(deck: str, runs: list[dict]) -> dict:
    """Доля невыбранных по децилям позиции и перестановочный тест."""
    facts = [row["fact_id"] for row in corpus.load_facts(deck)]
    if not facts:
        return {}
    position = {fact_id: index for index, fact_id in enumerate(facts)}
    counts = {fact_id: 0 for fact_id in facts}
    for run in runs:
        for fact_id in run["selected"]:
            if fact_id in counts:
                counts[fact_id] += 1
    total = len(runs)
    size = max(1, len(facts) // 10)
    buckets = []
    for decile in range(10):
        chunk = facts[decile * size:(decile + 1) * size] if decile < 9 else facts[9 * size:]
        if not chunk:
            continue
        missed = sum(1 for fact_id in chunk if counts[fact_id] == 0)
        buckets.append({"decile": decile + 1, "facts": len(chunk),
                        "missed_share": round(missed / len(chunk), 3)})
    observed = [bucket["missed_share"] for bucket in buckets]
    spread = max(observed) - min(observed) if observed else 0.0

    # перестановочный тест: те же счётчики, но перемешанные по позициям
    values = [counts[fact_id] for fact_id in facts]
    trials = 2000
    hits = 0
    rng = random.Random(20260101)
    for _ in range(trials):
        shuffled = values[:]
        rng.shuffle(shuffled)
        shares = []
        for decile in range(10):
            chunk = shuffled[decile * size:(decile + 1) * size] if decile < 9 else shuffled[9 * size:]
            if chunk:
                shares.append(sum(1 for value in chunk if value == 0) / len(chunk))
        if shares and (max(shares) - min(shares)) >= spread:
            hits += 1
    return {"deciles": buckets, "spread": round(spread, 3),
            "p_value": round(hits / trials, 3), "trials": trials}


def stability(deck: str, channel: str | None = None) -> dict:
    runs = runs_of(deck, channel)
    if len(runs) < 2:
        return {"deck": deck, "channel": channel, "runs": len(runs),
                "error": "нужно минимум два принятых прогона одного канала"}
    pairs = [jaccard(left["selected"], right["selected"])
             for left, right in itertools.combinations(runs, 2)]
    selected_counts: dict[str, int] = {}
    for run in runs:
        for fact_id in run["selected"]:
            selected_counts[fact_id] = selected_counts.get(fact_id, 0) + 1
    facts = [row["fact_id"] for row in corpus.load_facts(deck)]
    common = sum(1 for fact_id in facts if selected_counts.get(fact_id, 0) == len(runs))
    part = sum(1 for fact_id in facts if 0 < selected_counts.get(fact_id, 0) < len(runs))
    never = sum(1 for fact_id in facts if not selected_counts.get(fact_id, 0))
    position = decile_effect(deck, runs)
    return {
        "deck": deck, "channel": channel or "все принятые",
        "runs": len(runs), "stamps": [run["stamp"] for run in runs],
        "shuffled": any(run["order"].get("shuffled") for run in runs),
        "jaccard_mean": round(statistics.fmean(pairs), 3),
        "jaccard_min": round(min(pairs), 3),
        "selected_all": common, "selected_part": part, "selected_none": never,
        "selected_share_all": round(common / len(facts), 3) if facts else 0.0,
        "position": position, "trend": trend(position),
    }


def write(deck: str, body: dict) -> Path:
    """Имя файла включает канал: иначе второй прогон затирает отчёт первого."""
    suffix = str(body.get("channel") or "all").replace(" ", "-")
    json_path = corpus.ROOT / f"docs/facts/STABILITY-{deck}-{suffix}.json"
    corpus.write_json(json_path, body)
    md = corpus.ROOT / f"docs/facts/STABILITY-{deck}-{suffix}.md"
    lines = [f"# Шум прогонов: {deck}", "",
             f"канал: {body['channel']}, повторов {body['runs']}, "
             f"порядок перемешан: {'да' if body.get('shuffled') else 'нет'}", ""]
    if body.get("error"):
        lines += [body["error"], ""]
    else:
        lines += [
            f"Жаккар выбранных множеств: среднее {body['jaccard_mean']}, минимум {body['jaccard_min']}", "",
            f"выбраны всеми повторами: {body['selected_all']}, частью: {body['selected_part']}, "
            f"ни одним: {body['selected_none']}", "",
        ]
        position = body.get("position") or {}
        if position:
            lines += ["| дециль позиции | фактов | не выбрано |", "|---|---|---|"]
            for bucket in position["deciles"]:
                lines.append(f"| {bucket['decile']} | {bucket['facts']} | {bucket['missed_share']} |")
            lines += ["", f"разброс по децилям {position['spread']}, "
                          f"перестановочный тест p = {position['p_value']} "
                          f"({position['trials']} перестановок)", ""]
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md


def trend(position: dict) -> dict:
    """Есть ли монотонный тренд «чем дальше факт, тем чаще не выбран».

    Разброс по децилям отвечает на другой вопрос: где потери вообще кучкуются. Тезис про
    внимание требует роста, поэтому отдельно считается ранговая корреляция дециль → доля
    невыбранных. p-value перестановочного теста при этом ничего не говорит о тренде: он
    сдвигает факты между децилями и ломает кластеры похожих фактов, а не порядок.
    """
    buckets = position.get("deciles") or []
    if len(buckets) < 3:
        return {}
    shares = [bucket["missed_share"] for bucket in buckets]
    order = list(range(len(shares)))
    mean_r = (len(shares) - 1) / 2
    cov = sum((order[i] - mean_r) * (shares[i] - sum(shares) / len(shares))
              for i in range(len(shares)))
    var = sum((order[i] - mean_r) ** 2 for i in range(len(shares)))
    spread = sum((share - sum(shares) / len(shares)) ** 2 for share in shares) ** 0.5
    rho = cov / (var ** 0.5 * spread) if spread else 0.0
    first, last = shares[0], shares[-1]
    monotone = (all(shares[i] <= shares[i + 1] for i in range(len(shares) - 1))
                or all(shares[i] >= shares[i + 1] for i in range(len(shares) - 1)))
    if rho >= 0.5 and monotone:
        verdict = "тренд вверх: дальние факты теряются чаще"
    elif rho <= -0.5 and monotone:
        verdict = "тренд вниз: дальние факты теряются реже"
    else:
        verdict = "тренда нет: потери не привязаны к позиции"
    return {"spearman": round(rho, 3), "first": first, "last": last,
            "monotone": monotone, "verdict": verdict}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("deck")
    parser.add_argument("--channel", default=None)
    args = parser.parse_args()
    body = stability(args.deck, args.channel)
    out = write(args.deck, body)
    if body.get("error"):
        print(body["error"])
        return 2
    print(f"{args.deck}: повторов {body['runs']}, Жаккар {body['jaccard_mean']} (мин {body['jaccard_min']}), "
          f"всеми {body['selected_all']} / частью {body['selected_part']} / ни одним {body['selected_none']}")
    if body.get("position"):
        print(f"  разброс по децилям {body['position']['spread']}, "
              f"p = {body['position']['p_value']}")
    if body.get("trend"):
        print(f"  {body['trend']['verdict']} (Спирмен {body['trend']['spearman']})")
    print(f"→ {corpus.rel(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
