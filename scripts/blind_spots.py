"""Слепые зоны: тематические факты, которые не взял ни один прогон.

Два шага:
  list    — собрать список из прогонов (что никто не выбрал) → BLIND-SPOTS.md;
  review  — отдать список модели отдельным вопросом: факт важен для выводов, годится
            только как фон или к вопросу не относится. Массовый прогон теряет такие
            факты на внимании, точечный — нет.

Запуск:
  python3 docs/facts/blind_spots.py
  python3 docs/facts/blind_spots.py --review zcode
  python3 docs/facts/blind_spots.py --summary
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_analysis as ra  # noqa: E402

ROOT = Path(os.environ.get("CORPUS_ROOT") or Path.cwd()).resolve()
FACTS = ROOT / "docs/facts/facts.jsonl"
RUNS = ROOT / "docs/facts/runs"
OUT_LIST = ROOT / "docs/facts/BLIND-SPOTS.md"
OUT_REVIEW = ROOT / "docs/facts/BLIND-SPOTS-REVIEW.json"
OUT_MD = ROOT / "docs/facts/BLIND-SPOTS-REVIEW.md"

CONTRACT = """Верни ТОЛЬКО JSON:
{"verdicts": [{"fact_id": "F-…", "verdict": "material|background|irrelevant", "why": "до 15 слов"}]}
material — факт должен быть в выводах (влияет на понимание категории или на стратегию);
background — факт верен, но это фон/справка, в выводы не обязан;
irrelevant — к вопросу о покупке мясной гастрономии не относится.
Каждый fact_id из списка обязан получить ровно один вердикт.
"""


def selected_ids() -> set[str]:
    taken: set[str] = set()
    for path in sorted(RUNS.glob("*.json")):
        body = json.loads(path.read_text("utf-8"))
        for item in (body.get("answer") or {}).get("selected", []):
            if item.get("fact_id"):
                taken.add(item["fact_id"])
    return taken


def all_facts() -> dict[str, dict]:
    rows = {}
    for line in FACTS.read_text("utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[row["fact_id"]] = row
    return rows


def blind() -> list[dict]:
    facts = all_facts()
    taken = selected_ids()
    return [row for fid, row in facts.items() if row["thematic"] and fid not in taken]


def write_list() -> list[dict]:
    rows = sorted(blind(), key=lambda r: (r["deck"], r["page"]))
    lines = [
        "# Слепые зоны: тематические факты, которые не взял ни один прогон",
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
    print(f"слепых зон: {len(rows)} → {OUT_LIST.relative_to(ROOT)}")
    return rows


def review(backend: str, model: str) -> int:
    rows = write_list()
    prompt = (
        "Ты аналитик рынка FMCG. Ниже факты из колод, которые предыдущие прогоны не взяли "
        f"в опору выводов ({len(rows)} шт.).\n\n{ra.QUESTION}\n\n"
        + "\n".join(f"{r['fact_id']} | {r['deck']} стр.{r['page']} | {r['label']} | {r['value']}"
                    for r in rows)
        + "\n\n"
        + CONTRACT
    )
    print(f"{backend}: {len(rows)} фактов, промпт {len(prompt)} символов")
    answer, meta = (ra.call_zcode(prompt, keys=("verdicts",)) if backend == "zcode"
                    else ra.call_ollama(prompt, model, keys=("verdicts",)))
    data = json.loads(answer) if answer else None
    verdicts = {item["fact_id"]: item for item in (data or {}).get("verdicts", [])
                if isinstance(item, dict) and item.get("fact_id") in {r["fact_id"] for r in rows}}
    missing = [r["fact_id"] for r in rows if r["fact_id"] not in verdicts]
    stored = json.loads(OUT_REVIEW.read_text("utf-8")) if OUT_REVIEW.is_file() else {}
    stored[backend] = {"meta": meta, "verdicts": verdicts, "missing": missing}
    OUT_REVIEW.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"вердиктов {len(verdicts)} из {len(rows)}"
          + (f", без ответа {len(missing)}" if missing else ""))
    return 0 if len(verdicts) == len(rows) else 1


def summary() -> int:
    rows = blind()
    facts = {r["fact_id"]: r for r in rows}
    stored = json.loads(OUT_REVIEW.read_text("utf-8")) if OUT_REVIEW.is_file() else {}
    models = sorted(stored)
    if not models:
        print("нет разборов: сначала --review")
        return 2

    groups = {"material": [], "split": [], "background": [], "irrelevant": []}
    for fid, row in facts.items():
        votes = [stored[m]["verdicts"].get(fid, {}).get("verdict") for m in models]
        votes = [v for v in votes if v]
        if not votes:
            continue
        if all(v == "material" for v in votes):
            groups["material"].append(row)
        elif all(v in ("background", "irrelevant") for v in votes):
            groups["background" if any(v == "background" for v in votes) else "irrelevant"].append(row)
        else:
            groups["split"].append((row, votes))

    lines = [
        "# Разбор слепых зон",
        "",
        f"Участвовало моделей: {len(models)} ({', '.join(models)}). Фактов: {len(facts)}.",
        "",
        f"- обе считают материалом для выводов: {len(groups['material'])}",
        f"- обе считают фоном или не относят к вопросу: {len(groups['background']) + len(groups['irrelevant'])}",
        f"- разошлись: {len(groups['split'])}",
        "",
        "## Обе модели: факт должен быть в выводах",
        "",
    ]
    for row in sorted(groups["material"], key=lambda r: (r["deck"], r["page"])):
        why = stored[models[0]]["verdicts"].get(row["fact_id"], {}).get("why", "")
        lines.append(f"- {row['deck']} стр.{row['page']}: {row['label']} = {row['value']} — {why}")

    lines += ["", "## Разошлись", ""]
    for row, votes in sorted(groups["split"], key=lambda item: (item[0]["deck"], item[0]["page"])):
        pairs = "; ".join(f"{m}: {v}" for m, v in zip(models, votes))
        lines.append(f"- {row['deck']} стр.{row['page']}: {row['label']} = {row['value']} — {pairs}")

    lines += ["", "## Обе модели: фон или не к вопросу", ""]
    for row in sorted(groups["background"] + groups["irrelevant"], key=lambda r: (r["deck"], r["page"])):
        why = stored[models[0]]["verdicts"].get(row["fact_id"], {}).get("why", "")
        lines.append(f"- {row['deck']} стр.{row['page']}: {row['label']} = {row['value']} — {why}")

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"material {len(groups['material'])}, расходятся {len(groups['split'])}, "
          f"фон/не к вопросу {len(groups['background']) + len(groups['irrelevant'])}")
    print(f"→ {OUT_MD.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", choices=("zcode", "ollama"))
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--model", default="deepseek-v4.1-flash:cloud")
    args = parser.parse_args()
    if args.summary:
        return summary()
    if args.review:
        return review(args.review, args.model)
    write_list()
    return 0


if __name__ == "__main__":
    sys.exit(main())
