"""Сводка по корпусу: что модели взяли, что не взял никто.

Складывает COMPARISON-<колода>.json (а те уже посчитаны по принятым прогонам): сколько
фактов попало в анализ, какие тематические факты не выбрал ни один прогон, где модели
разошлись сильнее всего.

Запуск: CORPUS_ROOT=/path/to/project python3 $SKILL/summary_all.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402

OUT = corpus.ROOT / "docs/facts/SUMMARY.md"


def main() -> int:
    facts = {row["fact_id"]: row for row in corpus.load_facts()}
    taken: set[str] = set()
    per_deck = []

    for path in sorted((corpus.ROOT / "docs/facts").glob("COMPARISON-*.json")):
        body = json.loads(path.read_text("utf-8"))
        deck = body["deck"]
        counts = body["counts"]
        selected = {fid for fid, count in counts.items() if count > 0}
        taken |= selected
        deck_facts = [fid for fid, row in facts.items() if row["deck"] == deck]
        per_deck.append({
            "deck": deck,
            "facts": len(deck_facts),
            "selected": len(selected),
            "consensus": len(body["consensus"]),
            "single": len(body["single"]),
            "ignored": len(body["ignored"]),
            "clusters": len(body["clusters"]),
            "agreed": sum(1 for cluster in body["clusters"]
                          if len({claim["by"] for claim in cluster["claims"]}) == len(body["runs"])),
            "runs": len(body["runs"]),
        })

    if not per_deck:
        print("нет COMPARISON-*.json — сначала compare_analyses.py по колодам")
        return 2

    thematic = [fid for fid, row in facts.items() if row["thematic"]]
    blind = sorted((fid for fid in thematic if fid not in taken),
                   key=lambda fid: (facts[fid]["deck"], facts[fid]["page"]))

    lines = [
        "# Сводка по корпусу",
        "",
        f"Фактов в каноне: {len(facts)} (тематических {len(thematic)}).",
        f"Взял хотя бы один принятый прогон: {len(taken)} фактов "
        f"({len(taken) * 100 // max(len(facts), 1)} % корпуса, "
        f"{len([fid for fid in taken if facts[fid]['thematic']]) * 100 // max(len(thematic), 1)} % тематических).",
        f"Тематических, которые не взял никто: {len(blind)} "
        f"({len(blind) * 100 // max(len(thematic), 1)} % тематических).",
        "",
        "| колода | фактов | взято | сошлись все | выбрал один | не взял никто | выводов | согласны все |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in per_deck:
        lines.append(
            f"| {row['deck']} | {row['facts']} | {row['selected']} | {row['consensus']} | "
            f"{row['single']} | {row['ignored']} | {row['clusters']} | {row['agreed']} |"
        )

    lines += ["", "## Тематические факты, которые не взял никто", ""]
    if not blind:
        lines.append("Нет: каждый тематический факт попал хотя бы в один прогон.")
    for fid in blind[:80]:
        row = facts[fid]
        lines.append(f"- {row['deck']} стр.{row['page']}: {row['label']} = {row['value']} ({fid})")

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"колод с сравнением: {len(per_deck)}; взято фактов {len(taken)} из {len(facts)}; "
          f"тематических слепых зон {len(blind)}")
    print(f"→ {corpus.rel(OUT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
