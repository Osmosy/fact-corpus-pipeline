#!/usr/bin/env python3
"""Входной контроль: проверки Этапа 0 становятся кодом.

Что проверяется: значение факта стоит целой ячейкой на его странице, подпись —
дословная подстрока строки этой страницы, подпись и значение не совпадают в двух панелях
одной страницы, страница не является повтором другой, в ячейках нет многоточий.
Колода целиком: текст до первого якоря, рваные таблицы, повторяющиеся номера слайдов.

Коды с уровнем `error` (код выхода 1): `value_not_on_page`, `label_not_substring`.
Остальные — `warn`: они не портят канон, но требуют решения человека.

Выход: `docs/facts/INPUT-CHECK.json` и `INPUT-CHECK.md`.
  CORPUS_ROOT=/path/to/project python3 $SKILL/validate_input.py [--deck ИМЯ] [--quiet]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time

import corpus

PAGE = re.compile(r"(?m)^##\s+(?:Слайд|Slide|Страница|Page)\s+(\d+)\s*[—–-]?\s*(.*)$")
REPEAT = re.compile(r"повтор\s+слайда\s+(\d+)", re.I)
ELLIPSIS = ("…", "...")
ROW = re.compile(r"(?m)^\|[^\n]*\|[ \t]*$")
SEPARATOR = re.compile(r"^\|[\s:\-|]+\|$")

ERROR_CODES = ("value_not_on_page", "label_not_substring")
OUT_JSON = corpus.ROOT / "docs/facts/INPUT-CHECK.json"
OUT_MD = corpus.ROOT / "docs/facts/INPUT-CHECK.md"


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).replace("\u00a0", " ")).strip()


def norm_value(text: str) -> str:
    """Сравнение чисел не зависит от пробелов и десятичной запятой.

    Запятая превращается в точку только между цифрами: разделитель перечисления запятой
    таковой и остаётся, иначе «Cattera, +960 строчек» перестаёт быть границей числа.
    """
    # порядок важен: «8, 76%» — перечисление, а «54,8» — десятичная дробь
    value = re.sub(r"(?<=\d),(?=\d)", ".", norm(text).lower())
    return value.replace(" ", "")


def in_prose(value: str, body: str) -> bool:
    """Значение встречается в тексте страницы как отдельное число, а не часть другого."""
    needle = norm_value(value)
    if not needle:
        return False
    haystack = norm_value(body)
    pattern = r"(?<![\d.])" + re.escape(needle) + r"(?![\d.])"
    return re.search(pattern, haystack) is not None


def read_deck(deck: str) -> dict:
    path = corpus.ROOT / "decks" / deck / f"{deck}.md"
    if not path.is_file():
        raise SystemExit(f"нет колоды {path}")
    text = path.read_text("utf-8")
    marks = list(PAGE.finditer(text))
    pages: dict[int, dict] = {}
    findings: list[dict] = []

    head = text[: marks[0].start()] if marks else text
    if any(line.strip().startswith("|") for line in head.splitlines()):
        findings.append({"page": None, "code": "page_without_anchor", "level": "warn",
                         "detail": "строки таблицы до первого якоря «## Слайд N»"})

    for index, match in enumerate(marks):
        number = int(match.group(1))
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        body = text[match.end():end]
        title = norm(match.group(2))
        if number in pages:
            findings.append({"page": number, "code": "duplicate_page", "level": "warn",
                             "detail": f"слайд {number} встречается больше одного раза"})
            continue
        rows = [line for line in body.splitlines() if ROW.match(line)]
        counts = {len([cell for cell in line.strip().strip("|").split("|")])
                  for line in rows if not SEPARATOR.match(line.strip())}
        if len(counts) > 1:
            findings.append({"page": number, "code": "ragged_table", "level": "warn",
                             "detail": f"строки таблицы разной длины: {sorted(counts)}"})
        repeat = REPEAT.search(title)
        pages[number] = {"title": title, "body": body, "rows": rows,
                         "repeat_of": int(repeat.group(1)) if repeat else None}
    return {"pages": pages, "findings": findings}


def check_deck(deck: str, facts_by_page: dict[str, list[dict]]) -> dict:
    parsed = read_deck(deck)
    pages = parsed["pages"]
    findings = list(parsed["findings"])
    checked = 0

    for page_key, facts in sorted(facts_by_page.items(), key=lambda item: int(item[0])):
        page = int(page_key)
        info = pages.get(page)
        if info is None:
            for fact in facts:
                findings.append({"page": page, "code": "page_missing", "level": "error",
                                 "label": fact.get("label"), "value": fact.get("value"),
                                 "detail": "страницы нет в колоде"})
                checked += 1
            continue

        cells = {norm_value(cell) for row in info["rows"]
                 for cell in row.strip().strip("|").split("|")}
        page_text = norm(info["body"]).lower()

        for fact in facts:
            checked += 1
            label = norm(fact.get("label") or "")
            value = norm(fact.get("value") or "")
            base = {"page": page, "label": label, "value": value}

            if value and norm_value(value) not in cells:
                if in_prose(value, info["body"]):
                    findings.append({**base, "code": "value_in_prose", "level": "warn",
                                     "detail": "значение есть в тексте страницы, но не отдельной "
                                               "ячейкой — факт извлечён из прозы"})
                else:
                    findings.append({**base, "code": "value_not_on_page", "level": "error",
                                     "detail": "значения нет на этой странице ни ячейкой, ни в тексте"})
            if label and label.lower() not in page_text:
                findings.append({**base, "code": "label_not_substring", "level": "error",
                                 "detail": "подписи нет дословно ни в одной строке страницы"})
            if label and not value:
                findings.append({**base, "code": "empty_value", "level": "warn",
                                 "detail": "у факта нет значения"})
            if any(mark in label or mark in value for mark in ELLIPSIS):
                findings.append({**base, "code": "truncated_cell", "level": "warn",
                                 "detail": "в подписи или значении многоточие — ячейка обрезана"})
            if info["repeat_of"] is not None:
                findings.append({**base, "code": "repeated_slide", "level": "warn",
                                 "detail": f"страница повторяет слайд {info['repeat_of']}"})
            if label and value:
                _row, reason = corpus.resolve_row(deck, page, label, value)
                if reason and reason.startswith("неоднозначно"):
                    findings.append({**base, "code": "panel_ambiguous", "level": "warn",
                                     "detail": reason})

    errors = sum(1 for item in findings if item["level"] == "error")
    return {"deck": deck, "pages": len(pages), "facts": checked,
            "errors": errors, "warnings": len(findings) - errors, "findings": findings}


def load_page_facts() -> dict:
    if not corpus.PAGE_FACTS.is_file():
        raise SystemExit(f"нет {corpus.rel(corpus.PAGE_FACTS)} — входной контроль не на чем делать")
    return json.loads(corpus.PAGE_FACTS.read_text("utf-8"))


def write_report(decks: list[dict]) -> dict:
    totals = {"pages": sum(d["pages"] for d in decks), "facts": sum(d["facts"] for d in decks),
              "errors": sum(d["errors"] for d in decks),
              "warnings": sum(d["warnings"] for d in decks)}
    report = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "totals": totals,
              "decks": {d["deck"]: d for d in decks}}
    corpus.write_json(OUT_JSON, report)

    lines = ["# Входной контроль", "",
             f"Колод {len(decks)}, страниц {totals['pages']}, фактов {totals['facts']}: "
             f"ошибок {totals['errors']}, предупреждений {totals['warnings']}.", "",
             "Ошибки (код 1) — значение не на своей странице, подпись не найдена дословно. "
             "Предупреждения канон не портят, но требуют решения.", ""]
    for deck in decks:
        lines.append(f"## {deck['deck']}")
        lines.append("")
        lines.append(f"страниц {deck['pages']}, фактов {deck['facts']}, "
                     f"ошибок {deck['errors']}, предупреждений {deck['warnings']}")
        lines.append("")
        if not deck["findings"]:
            lines.append("чисто")
            lines.append("")
            continue
        counts: dict[str, int] = {}
        for item in deck["findings"]:
            counts[item["code"]] = counts.get(item["code"], 0) + 1
        lines.append("| код | уровень | сколько |")
        lines.append("|---|---|---|")
        for code, count in sorted(counts.items()):
            level = "error" if code in ERROR_CODES else "warn"
            lines.append(f"| `{code}` | {level} | {count} |")
        lines.append("")
        for item in deck["findings"][:40]:
            where = f"стр.{item['page']}" if item.get("page") else "до первого якоря"
            label = item.get("label") or ""
            value = item.get("value") or ""
            tail = f" — {label} = {value}" if label or value else ""
            lines.append(f"- {where}: `{item['code']}`{tail} ({item['detail']})")
        if len(deck["findings"]) > 40:
            lines.append(f"- … ещё {len(deck['findings']) - 40} в JSON")
        lines.append("")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deck", action="append", help="только эта колода (можно несколько)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    data = load_page_facts()
    decks = sorted(data.get("decks", {}))
    if args.deck:
        missing = [name for name in args.deck if name not in decks]
        if missing:
            print(f"нет данных по колодам: {', '.join(missing)}")
            return 2
        decks = args.deck

    results = [check_deck(deck, {page: body.get("facts", []) for page, body
                                 in data["decks"][deck].get("pages", {}).items()})
               for deck in decks]
    report = write_report(results)
    totals = report["totals"]
    if not args.quiet:
        for deck in results:
            print(f"{deck['deck']}: страниц {deck['pages']}, фактов {deck['facts']}, "
                  f"ошибок {deck['errors']}, предупреждений {deck['warnings']}")
        print(f"итого: фактов {totals['facts']}, ошибок {totals['errors']}, "
              f"предупреждений {totals['warnings']} → {corpus.rel(OUT_JSON)}")
    return 1 if totals["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
