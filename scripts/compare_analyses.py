"""Сравнение анализов: что выбрали модели, где сошлись, где разошлись.

На вход — docs/facts/runs/<колода>.<канал>-<штамп>.json. В счёт идут только принятые
прогоны: непустой ответ и пустой список `problems` (см. corpus.load_runs). От одного
канала по умолчанию берётся последний прогон, иначе перезапуск колоды добавлял бы
«ещё одну модель» и переворачивал срезы.

На выход — COMPARISON-<колода>.md и .json:

  consensus  — факты, выбранные всеми прогонами;
  majority   — выбранные большинством;
  single     — выбранные ровно одним прогоном (повод проверить, не пропуск ли это);
  ignored    — не выбрал никто (кандидаты в слепые зоны);
  clusters   — выводы, сгруппированные по смыслу.

Выводы склеиваются, если пересечение их fact_ids близко к полному (Жаккар ≥ 0.5) **или**
тексты похожи (difflib ≥ порога). Одного общего факта недостаточно: широкий факт вроде
размера выборки иначе склеит разные выводы.

Запуск:
  CORPUS_ROOT=/path/to/project python3 $SKILL/compare_analyses.py <колода>
  … --all-runs            учитывать все прогоны канала, а не последний
  … --include-rejected    включить отклонённые (для разбора причин отказа)
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402

SIMILAR = 0.55
JACCARD = 0.5


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("ё", "е")).strip()


def jaccard(left: set, right: set) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def same_claim(claim: dict, other: dict, similarity: float, overlap: float) -> bool:
    if jaccard(claim["facts"], other["facts"]) >= overlap:
        return True
    return difflib.SequenceMatcher(None, norm(claim["text"]), norm(other["text"])).ratio() >= similarity


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("deck")
    parser.add_argument("--all-runs", action="store_true")
    parser.add_argument("--include-rejected", action="store_true")
    parser.add_argument("--similarity", type=float, default=SIMILAR)
    parser.add_argument("--overlap", type=float, default=JACCARD, help="порог Жаккара для выводов")
    args = parser.parse_args()

    deck = args.deck
    out_md = corpus.ROOT / f"docs/facts/COMPARISON-{deck}.md"
    out_json = corpus.ROOT / f"docs/facts/COMPARISON-{deck}.json"

    runs = corpus.load_runs(deck, include_rejected=args.include_rejected, all_runs=args.all_runs)
    if not runs:
        print(f"нет принятых прогонов для {deck}")
        return 2

    facts = {row["fact_id"]: row for row in corpus.load_facts(deck)}

    selected = {}
    for run in runs:
        selected[run["name"]] = {
            item.get("fact_id") for item in run["body"]["answer"].get("selected", [])
            if isinstance(item, dict) and item.get("fact_id") in facts
        }

    names = list(selected)
    counts = {fid: sum(fid in selected[name] for name in names) for fid in facts}
    by_page = lambda fid: (facts[fid]["page"], fid)  # noqa: E731
    consensus = sorted((fid for fid, n in counts.items() if n == len(names)), key=by_page)
    majority = sorted((fid for fid, n in counts.items() if n > len(names) / 2), key=by_page)
    single = sorted((fid for fid, n in counts.items() if n == 1), key=by_page)
    ignored = sorted((fid for fid, n in counts.items() if n == 0), key=by_page)

    claims = []
    for run in runs:
        for item in run["body"]["answer"].get("conclusions", []):
            if not isinstance(item, dict):
                continue
            text = (item.get("text") or "").strip()
            if text:
                claims.append({"text": text, "facts": set(item.get("fact_ids") or []), "by": run["name"]})

    clusters: list[dict] = []
    for claim in claims:
        for cluster in clusters:
            if any(same_claim(claim, member, args.similarity, args.overlap) for member in cluster["claims"]):
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
        f"Прогонов: {len(runs)} — " + ", ".join(
            f"{r['name']}: {len(r['body']['answer'].get('selected', []))} фактов, "
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

    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    corpus.write_json(out_json, {
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
    })
    print(f"прогонов {len(runs)}: consensus {len(consensus)}, single {len(single)}, ignored {len(ignored)}, "
          f"кластеров выводов {len(clusters)} (согласны все {len(agreed)})")
    print(f"→ {corpus.rel(out_md)}, {corpus.rel(out_json)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
