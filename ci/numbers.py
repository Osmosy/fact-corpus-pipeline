#!/usr/bin/env python3
"""Сверка чисел в документах с отчётом: размеченное число обязано совпасть.

Разметка в markdown: `<!-- n:blind.total -->41<!-- /n -->`. Значения берутся из снимка
`docs/case-study.report.json` — это REPORT.json кейса, только агрегаты, без подписей и
значений закрытых колод.

Что проверяется:
  - размеченное число расходится со снимком → находка (код 1);
  - ключ размечен, но его нет в снимке → находка;
  - рядом со словами «фактов», «слепых», «тематических», «обязательств» стоит число без
    разметки → предупреждение (не ошибка: не всякая цифра — число корпуса);
  - `<!-- было -->119<!-- /было -->` — историческое значение: сверять не с чем, из проверки
    исключается. Так помечаются числа «до правок» в аудите; текущие всё равно размечены ключами;
  - ключи, связанные по смыслу (`owner_exceptions.with_marker` и `.total`), обязаны совпадать:
    иначе текст остаётся согласованным со снимком, а смысл — нет.

Граница проверки: снимок копируется из проекта вручную, поэтому сверяется текст со снимком,
а не снимок с корпусом. Числа корпуса проверяются только на стороне проекта.

Запуск: python3 ci/numbers.py [--quiet]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "docs/case-study.report.json"
DOCS = ("README.md", "SKILL.md", "docs/case-study.md", "docs/audit-2026-11.md")
# соотношения между ключами: если разойдутся, текст останется «правильным», а смысл — нет
PAIRS = (("owner_exceptions.with_marker", "owner_exceptions.total",
          "у каждого исключения должен быть маркер панели"),)
MARK = re.compile(r"<!--\s*n:([A-Za-z0-9_.\-]+)\s*-->(.*?)<!--\s*/n\s*-->", re.S)
# историческое значение: сверять не с чем — оно описывает состояние до правок, а не текущее
HIST = re.compile(r"<!--\s*было\s*-->(.*?)<!--\s*/было\s*-->", re.S)


def same(left: str, right: str) -> bool:
    """«6,3» и «6.3» — одно число; пробелы и знак процента не значимы."""
    def norm(value: str) -> str:
        return str(value).replace(",", ".").replace(" ", "").replace("%", "").strip()
    return norm(left) == norm(right)
NEAR = re.compile(r"(фактов|факта|слепых|тематических|обязательств|кластеров)\D{0,40}(\d{1,4})", re.I)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if not SNAPSHOT.is_file():
        print(f"нет снимка {SNAPSHOT.relative_to(ROOT)} — сначала report.py на проекте, "
              "затем скопировать агрегаты сюда")
        return 2
    numbers = json.loads(SNAPSHOT.read_text("utf-8"))

    problems: list[str] = []
    for left, right, why in PAIRS:
        if left in numbers and right in numbers and numbers[left] != numbers[right]:
            problems.append(f"снимок: `{left}` = {numbers[left]}, а `{right}` = {numbers[right]} — {why}")
    warnings: list[str] = []
    marked = 0
    historical = 0
    historical = 0
    for name in DOCS:
        path = ROOT / name
        if not path.is_file():
            continue
        text = path.read_text("utf-8")
        for key, value in MARK.findall(text):
            marked += 1
            if key not in numbers:
                problems.append(f"{name}: ключ `{key}` размечен, но его нет в снимке")
                continue
            expected = str(numbers[key])
            if not same(value, expected):
                problems.append(f"{name}: `{key}` = {value.strip()}, в отчёте {expected}")
        historical += len(HIST.findall(text))
        # исторические значения вырезаются до поиска «числа без разметки»: сверять их не с чем
        clean = MARK.sub(lambda match: " " * len(match.group(0)), HIST.sub(" ", text))
        for word, number in NEAR.findall(clean):
            warnings.append(f"{name}: «{word} … {number}» без разметки — если это число "
                            f"корпуса, разметьте ключом")

    if not args.quiet:
        for item in problems:
            print("ошибка:", item)
        for item in warnings[:10]:
            print("предупреждение:", item)
        if len(warnings) > 10:
            print(f"предупреждений всего: {len(warnings)}")
        print(f"чисел размечено: {marked}, исторических: {historical}, "
              f"расхождений: {len(problems)}, предупреждений: {len(warnings)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
