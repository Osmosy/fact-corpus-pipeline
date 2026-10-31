"""Сводка по всему корпусу: что модели взяли, что не взял никто.

Складывает COMPARISON-<колода>.json и прогоны из runs/, чтобы видеть картину не по колоде,
а по материалу: сколько фактов вообще попало в анализ, какие тематические факты не выбрал
ни один прогон (слепые зоны) и где модели разошлись сильнее всего.

Запуск: python3 docs/facts/summary_all.py
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CORPUS_ROOT") or Path.cwd()).resolve()
FACTS = ROOT / "docs/facts/facts.jsonl"
COMPARISONS = ROOT / "docs/facts"
OUT = COMPARISONS / "SUMMARY.md"


def main() -> int:
    facts: dict[str, dict] = {}
    for line in FACTS.read_text("utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            facts[row["fact_id"]] = row

    taken: set[str] = set()
    per_deck = []
    for path in sorted(COMPARISONS.glob("COMPARISON-*.json")):
        body = json.loads(path.read_text("utf-8"))
        deck = body["deck"]
        counts = body["counts"]
        selected = {fid for fid, n in counts.items() if n > 0}
        taken |= selected
        deck_facts = [fid for fid in facts if facts[fid]["deck"] == deck]
        per_deck.append(
            {
                "deck": deck,
                "facts": len(deck_facts),
                "selected": len(selected),
                "consensus": len(body["consensus"]),
                "single": len(body["single"]),
                "ignored": len(body["ignored"]),
                "clusters": len(body["clusters"]),
                "agreed": sum(1 for c in body["clusters"]
                              if len({cl["by"] for cl in c["claims"]}) == len(body["runs"])),
            }
        )

    thematic = [fid for fid, row in facts.items() if row["thematic"]]
    blind = sorted((fid for fid in thematic if fid not in taken),
                   key=lambda f: (facts[f]["deck"], facts[f]["page"]))

    lines = [
        "# Сводка по корпусу",
        "",
        f"Фактов в каноне: {len(facts)} (тематических {len(thematic)}).",
        f"Взял хотя бы один прогон: {len(taken)} фактов "
        f"({len(taken) * 100 // max(len(facts), 1)} % корпуса).",
        f"Тематических, которые не взял никто: {len(blind)}.",
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
    print(f"→ {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
