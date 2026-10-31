"""Сравнение анализов: что выбрали модели, где сошлись, где разошлись.

На вход — файлы docs/facts/runs/<deck>.<backend>-<stamp>.json (по одному на модель/прогон).
На выход — COMPARISON.md (для чтения) и COMPARISON.json (машиночитаемо):

  consensus  — факты, выбранные всеми прогонами;
  majority   — выбранные большинством;
  single     — выбранные ровно одним прогоном (повод проверить, не пропуск ли это);
  ignored    — не выбрал никто (кандидаты в «малозначимые» и в «пропущенные»);
  conclusions — кластеры похожих выводов с указанием, кто их сформулировал.

Похожесть выводов — по пересечению fact_ids и по difflib, порог 0.55: этого хватает,
чтобы собрать одинаковые по смыслу формулировки и не склеить разные.
"""
import difflib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CORPUS_ROOT") or Path.cwd()).resolve()
RUNS = ROOT / "docs/facts/runs"
FACTS = ROOT / "docs/facts/facts.jsonl"
OUT_MD = None  # задаётся по имени колоды в main()
OUT_JSON = None
SIMILAR = 0.55


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("ё", "е")).strip()


def main() -> int:
    global OUT_MD, OUT_JSON
    if len(sys.argv) < 2:
        print("укажи колоду: compare_analyses.py <колода>")
        return 2
    deck = sys.argv[1]
    OUT_MD = ROOT / f"docs/facts/COMPARISON-{deck}.md"
    OUT_JSON = ROOT / f"docs/facts/COMPARISON-{deck}.json"
    runs = []
    for path in sorted(RUNS.glob(f"{deck}.*.json")):
        body = json.loads(path.read_text("utf-8"))
        if not body.get("answer"):
            continue
        runs.append({"name": f"{body['backend']} ({path.name.split('.')[1]})", "path": path, "body": body})
    if len(runs) < 1:
        print(f"нет прогонов для {deck}")
        return 2

    facts = {}
    for line in FACTS.read_text("utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row["deck"] == deck:
                facts[row["fact_id"]] = row

    selected = {}
    for run in runs:
        selected[run["name"]] = {item.get("fact_id") for item in run["body"]["answer"].get("selected", [])
                                 if item.get("fact_id") in facts}

    names = list(selected)
    counts = {fid: sum(fid in selected[name] for name in names) for fid in facts}
    consensus = sorted((fid for fid, n in counts.items() if n == len(names)), key=lambda f: facts[f]["page"])
    majority = sorted((fid for fid, n in counts.items() if n > len(names) / 2), key=lambda f: facts[f]["page"])
    single = sorted((fid for fid, n in counts.items() if n == 1), key=lambda f: facts[f]["page"])
    ignored = sorted((fid for fid, n in counts.items() if n == 0), key=lambda f: facts[f]["page"])

    claims = []
    for run in runs:
        for item in run["body"]["answer"].get("conclusions", []):
            text = (item.get("text") or "").strip()
            if text:
                claims.append({"text": text, "facts": set(item.get("fact_ids") or []), "by": run["name"]})
    clusters: list[dict] = []
    for claim in claims:
        for cluster in clusters:
            head = cluster["claims"][0]
            overlap = claim["facts"] & head["facts"]
            similar = difflib.SequenceMatcher(None, norm(claim["text"]), norm(head["text"])).ratio()
            if overlap or similar >= SIMILAR:
                cluster["claims"].append(claim)
                break
        else:
            clusters.append({"claims": [claim]})

    agreed = [c for c in clusters if len({cl["by"] for cl in c["claims"]}) == len(names)]
    partial = [c for c in clusters if 1 < len({cl["by"] for cl in c["claims"]}) < len(names)]
    lonely = [c for c in clusters if len({cl["by"] for cl in c["claims"]}) == 1]

    lines = [
        f"# Сравнение анализов: {deck}",
        "",
        f"Прогонов: {len(runs)} — " + ", ".join(f"{r['name']}: {len(r['body']['answer'].get('selected', []))} фактов, "
                                               f"{len(r['body']['answer'].get('conclusions', []))} выводов" for r in runs),
        "",
        f"Всего фактов в колоде: {len(facts)}",
        "",
        "| | фактов |",
        "|---|---|",
        f"| выбрали все прогоны | {len(consensus)} |",
        f"| выбрало большинство | {len(majority)} |",
        f"| выбрал ровно один | {len(single)} |",
        f"| не выбрал никто | {len(ignored)} |",
        "",
        "## Выводы: совпадения и расхождения",
        "",
        ("" if len(runs) > 1 else
         "> Один прогон: сравнение вырождено — «согласны все» и «только у одного» это одни и те же\n"
         "> выводы. Срезы имеют смысл со второго прогона.\n"),
        f"- согласны все ({len(agreed)})",
        f"- согласны частично ({len(partial)})",
        f"- только у одного прогона ({len(lonely)})",
        "",
    ]
    for title, group in (("Согласны все", agreed), ("Согласны не все", partial), ("Только у одного", lonely)):
        if not group:
            continue
        lines += [f"### {title}", ""]
        for cluster in group:
            head = cluster["claims"][0]
            who = ", ".join(sorted({c["by"] for c in cluster["claims"]}))
            lines.append(f"- {head['text']}  \n  факты: {', '.join(sorted(head['facts'])) or '—'}; источники: {who}")
        lines.append("")

    if consensus:
        lines += ["## Факты, на которых сошлись все", ""]
        for fid in consensus[:40]:
            row = facts[fid]
            lines.append(f"- {fid} стр.{row['page']}: {row['label']} = {row['value']}")
        lines.append("")

    lines += ["## Факты, которые не выбрал никто (первые 40)", ""]
    for fid in ignored[:40]:
        row = facts[fid]
        lines.append(f"- {fid} стр.{row['page']}: {row['label']} = {row['value']}")
    lines.append("")

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    OUT_JSON.write_text(
        json.dumps(
            {
                "deck": deck,
                "runs": [r["name"] for r in runs],
                "counts": counts,
                "consensus": consensus,
                "majority": majority,
                "single": single,
                "ignored": ignored,
                "clusters": [
                    {"claims": [{"text": c["text"], "facts": sorted(c["facts"]), "by": c["by"]}
                                for c in cluster["claims"]]}
                    for cluster in clusters
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"прогонов {len(runs)}: consensus {len(consensus)}, single {len(single)}, ignored {len(ignored)}, "
          f"кластеров выводов {len(clusters)} (согласны все {len(agreed)})")
    print(f"→ {OUT_MD.relative_to(ROOT)}, {OUT_JSON.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
