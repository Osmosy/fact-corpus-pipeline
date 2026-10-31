"""Слепые зоны: тематические факты, которые не взял ни один принятый прогон.

Три шага:
  list    — собрать список (что никто не выбрал) → BLIND-SPOTS.md;
  review  — отдать список модели отдельным вопросом: факт важен для выводов, годится
            только как фон или к вопросу не относится. Массовый прогон теряет такие
            факты на внимании, точечный — нет;
  summary — свести вердикты: материал / разошлись / фон / неполный разбор.

Запуск:
  CORPUS_ROOT=/path/to/project python3 $SKILL/blind_spots.py
  CORPUS_ROOT=/path/to/project python3 $SKILL/blind_spots.py --review zcode
  CORPUS_ROOT=/path/to/project python3 $SKILL/blind_spots.py --summary
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402
import run_analysis as ra  # noqa: E402

OUT_LIST = corpus.ROOT / "docs/facts/BLIND-SPOTS.md"
OUT_REVIEW = corpus.ROOT / "docs/facts/BLIND-SPOTS-REVIEW.json"
OUT_MD = corpus.ROOT / "docs/facts/BLIND-SPOTS-REVIEW.md"

VERDICTS = ("material", "background", "irrelevant")

CONTRACT = """Верни ТОЛЬКО JSON:
{"verdicts": [{"fact_id": "F-…", "verdict": "material|background|irrelevant", "why": "до 15 слов"}]}
material — факт должен быть в выводах (влияет на понимание вопроса или на стратегию);
background — факт верен, но это фон/справка, в выводы не обязан;
irrelevant — к вопросу исследования не относится.
Каждый fact_id из списка обязан получить ровно один вердикт.
"""


def selected_ids() -> set[str]:
    """Что взяли принятые прогоны (последний прогон на канал; отклонённые не в счёт)."""
    taken: set[str] = set()
    for path in sorted(corpus.RUNS.glob("*.json")):
        deck = path.name.split(".")[0]
        for run in corpus.load_runs(deck):
            if run["path"] != path:
                continue
            for item in run["body"]["answer"].get("selected", []):
                if isinstance(item, dict) and item.get("fact_id"):
                    taken.add(item["fact_id"])
    return taken


def blind() -> list[dict]:
    taken = selected_ids()
    return [row for row in corpus.load_facts() if row["thematic"] and row["fact_id"] not in taken]


def write_list() -> list[dict]:
    rows = sorted(blind(), key=lambda r: (r["deck"], r["page"]))
    lines = [
        "# Слепые зоны: тематические факты, которые не взял ни один принятый прогон",
        "",
        f"Всего: {len(rows)}. Это не приговор фактам — массовый прогон теряет их на внимании,",
        "поэтому дальше каждый проверяется отдельным вопросом.",
        "",
        "| fact_id | колода | стр. | факт | значение |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(f"| {row['fact_id']} | {row['deck']} | {row['page']} | "
                     f"{row['label'].replace('|', '/')} | {row['value']} |")
    OUT_LIST.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"слепых зон: {len(rows)} → {corpus.rel(OUT_LIST)}")
    return rows


def review(backend: str, model: str) -> int:
    config = corpus.load_config(required=("question", "role"))
    rows = write_list()
    prompt = (
        f"Ты {config['role']}. Ниже факты из колод, которые предыдущие прогоны не взяли "
        f"в опору выводов ({len(rows)} шт.).\n\n{config['question']}\n\n"
        + "\n".join(f"{r['fact_id']} | {r['deck']} стр.{r['page']} | {r['label']} | {r['value']}"
                    for r in rows)
        + "\n\n"
        + CONTRACT
    )
    print(f"{backend}: {len(rows)} фактов, промпт {len(prompt)} символов")
    answer, meta = (ra.call_zcode(prompt, keys=("verdicts",)) if backend == "zcode"
                    else ra.call_ollama(prompt, model, keys=("verdicts",)))
    data = json.loads(answer) if answer else None
    known = {row["fact_id"] for row in rows}
    verdicts = {item["fact_id"]: item for item in (data or {}).get("verdicts", [])
                if isinstance(item, dict) and item.get("fact_id") in known}
    missing = [row["fact_id"] for row in rows if row["fact_id"] not in verdicts]
    stored = json.loads(OUT_REVIEW.read_text("utf-8")) if OUT_REVIEW.is_file() else {}
    stored[backend] = {"meta": meta, "verdicts": verdicts, "missing": missing}
    corpus.write_json(OUT_REVIEW, stored)
    print(f"вердиктов {len(verdicts)} из {len(rows)}"
          + (f", без ответа {len(missing)}" if missing else ""))
    return 0 if len(verdicts) == len(rows) else 1


def summary() -> int:
    facts = {row["fact_id"]: row for row in blind()}
    stored = json.loads(OUT_REVIEW.read_text("utf-8")) if OUT_REVIEW.is_file() else {}
    models = sorted(stored)
    if not models:
        print("нет разборов: сначала --review")
        return 2

    groups: dict[str, list] = {"material": [], "split": [], "background": [], "irrelevant": [],
                              "incomplete": []}
    for fid, row in facts.items():
        votes = {model: stored[model]["verdicts"].get(fid, {}).get("verdict") for model in models}
        answered = {model: value for model, value in votes.items() if value in VERDICTS}
        if len(answered) < len(models):
            groups["incomplete"].append((row, votes))
            continue
        values = list(answered.values())
        if all(value == "material" for value in values):
            groups["material"].append(row)
        elif all(value in ("background", "irrelevant") for value in values):
            groups["background" if "background" in values else "irrelevant"].append(row)
        else:
            groups["split"].append((row, answered))

    def why(fid: str) -> str:
        for model in models:
            text = stored[model]["verdicts"].get(fid, {}).get("why")
            if text:
                return text
        return ""

    lines = [
        "# Разбор слепых зон",
        "",
        f"Участвовало моделей: {len(models)} ({', '.join(models)}). Фактов: {len(facts)}.",
        "",
        f"- все считают материалом для выводов: {len(groups['material'])}",
        f"- все считают фоном или не относят к вопросу: "
        f"{len(groups['background']) + len(groups['irrelevant'])}",
        f"- разошлись: {len(groups['split'])}",
    ]
    if groups["incomplete"]:
        lines.append(f"- ответили не все модели, в счёт не идут: {len(groups['incomplete'])}")
    lines += ["", "## Все модели: факт должен быть в выводах", ""]
    for row in sorted(groups["material"], key=lambda r: (r["deck"], r["page"])):
        lines.append(f"- {row['deck']} стр.{row['page']}: {row['label']} = "
                     f"{row['value']} — {why(row['fact_id'])}")

    lines += ["", "## Разошлись", ""]
    for row, votes in sorted(groups["split"], key=lambda item: (item[0]["deck"], item[0]["page"])):
        pairs = "; ".join(f"{model}: {verdict}" for model, verdict in votes.items())
        lines.append(f"- {row['deck']} стр.{row['page']}: {row['label']} = {row['value']} — {pairs}")

    lines += ["", "## Все модели: фон или не к вопросу", ""]
    for row in sorted(groups["background"] + groups["irrelevant"], key=lambda r: (r["deck"], r["page"])):
        lines.append(f"- {row['deck']} стр.{row['page']}: {row['label']} = "
                     f"{row['value']} — {why(row['fact_id'])}")

    if groups["incomplete"]:
        lines += ["", "## Ответили не все модели (нужен повторный разбор)", ""]
        for row, votes in sorted(groups["incomplete"], key=lambda item: (item[0]["deck"], item[0]["page"])):
            pairs = "; ".join(f"{model}: {verdict or '—'}" for model, verdict in votes.items())
            lines.append(f"- {row['deck']} стр.{row['page']}: {row['label']} = {row['value']} — {pairs}")

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"material {len(groups['material'])}, расходятся {len(groups['split'])}, "
          f"фон/не к вопросу {len(groups['background']) + len(groups['irrelevant'])}, "
          f"неполно {len(groups['incomplete'])}")
    print(f"→ {corpus.rel(OUT_MD)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", choices=("zcode", "ollama"))
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--model", default=corpus.LLM_MODEL)
    args = parser.parse_args()
    if args.summary:
        return summary()
    if args.review:
        return review(args.review, args.model)
    write_list()
    return 0


if __name__ == "__main__":
    sys.exit(main())
