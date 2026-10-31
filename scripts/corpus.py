"""Общий слой конвейера: конфиг корпуса, канон фактов, прогоны, разбор ответов модели.

Все скрипты берут пути и предметные настройки отсюда, чтобы «работает на любом корпусе»
было правдой: вопрос исследования, роль модели, основы тематических слов и автор решений
живут в docs/facts/config.json, а не в коде.

Переменные окружения (все необязательные, кроме CORPUS_ROOT по смыслу):
  CORPUS_ROOT  — корень проекта с данными (по умолчанию текущий каталог);
  LLM_URL      — OpenAI-совместимый адрес чата (по умолчанию локальный шлюз);
  LLM_MODEL    — модель для канала ollama;
  ZCODE_BIN    — исполняемый файл пула Z.AI;
  APPENDIX_INFO— путь к приложению «Справочно» относительно корня;
  GRACE_REGISTRY — путь к установленному реестру vector-grace/registry.
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(os.environ.get("CORPUS_ROOT") or Path.cwd()).resolve()

FACTS = ROOT / "docs/facts/facts.jsonl"
CONFIG = ROOT / "docs/facts/config.json"
PLAN = ROOT / "docs/facts/plan.json"
DECISIONS = ROOT / "docs/facts/fact_decisions.json"
DISPOSITIONS = ROOT / "docs/registry/dispositions.json"
PAGE_FACTS = ROOT / "docs/registry/page_facts.json"
REQUIREMENTS = ROOT / "docs/requirements-registry.jsonl"
RUNS = ROOT / "docs/facts/runs"
REJECTED_FACTS = ROOT / "docs/facts/facts-rejected.jsonl"

LLM_URL = os.environ.get("LLM_URL", "http://127.0.0.1:11434/v1/chat/completions")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-v4.1-flash:cloud")
ZCODE_BIN = os.environ.get("ZCODE_BIN", str(Path.home() / ".local/bin/zcode-start-plan"))

TARGETS = ("conclusions", "info", "waive")

CONFIG_KEYS = ("question", "role", "theme_stems", "decided_by")


def load_config(path: Path | None = None, required: tuple[str, ...] = CONFIG_KEYS) -> dict:
    """Настройки корпуса: каждый скрипт просит только те поля, которые ему нужны.

    Сборка канона живёт без `decided_by`, а решения — без `question`; требовать всё сразу
    значит заставлять заполнять лишнее и падать там, где поле не используется.
    """
    file = path or CONFIG
    if not file.is_file():
        raise SystemExit(
            f"нет {file} — скопируй scripts/examples/config.example.json в docs/facts/config.json\n"
            f"и заполни поля: {', '.join(required)}"
        )
    data = json.loads(file.read_text("utf-8"))
    missing = [key for key in required if not data.get(key)]
    if missing:
        raise SystemExit(f"{file}: для этого шага не заполнены поля {', '.join(missing)}")
    if data.get("theme_stems") and isinstance(data["theme_stems"], str):
        data["theme_stems"] = [word.strip() for word in data["theme_stems"].split(",") if word.strip()]
    if "theme_stems" in required and not isinstance(data["theme_stems"], list):
        raise SystemExit(f"{file}: theme_stems должен быть списком основ слов")
    return data


def load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def load_facts(deck: str | None = None) -> list[dict]:
    rows = load_jsonl(FACTS)
    return [row for row in rows if deck is None or row["deck"] == deck]


def load_runs(deck: str, include_rejected: bool = False, all_runs: bool = False,
              report: list | None = None) -> list[dict]:
    """Прогоны колоды, готовые к сравнению.

    По контракту в сравнение идут только принятые: непустой ответ и пустой список проблем.
    Отклонённые включаются флагом --include-rejected (для разбора, почему прогон не принят).
    По умолчанию от одного канала берётся последний прогон: иначе перезапуск колоды
    добавляет «ещё одну модель» и переворачивает срезы «выбрали все / ровно один».

    Если последний прогон канала отклонён, берётся предыдущий принятый — и это попадает
    в `report`: молча подменять свежий прогон старым значит скрывать неудачный перезапуск.
    """
    items = []
    for path in sorted(RUNS.glob(f"{deck}.*.json")):
        try:
            body = json.loads(path.read_text("utf-8"))
        except json.JSONDecodeError:
            continue
        problems = body.get("problems") or []
        answer = body.get("answer")
        if not answer and not problems:
            continue
        items.append({
            "backend": body.get("backend") or path.name.split(".")[1],
            "stamp": path.stem, "path": path, "body": body,
            "problems": problems, "accepted": bool(answer) and not problems,
        })

    eligible = [item for item in items if include_rejected or item["accepted"]]
    if not all_runs:
        latest: dict[str, dict] = {}
        for item in eligible:
            latest[item["backend"]] = item
        if report is not None:
            for backend, taken in latest.items():
                newer = [item for item in items
                         if item["backend"] == backend and item["stamp"] > taken["stamp"]
                         and not item["accepted"]]
                if newer:
                    report.append({
                        "backend": backend,
                        "taken": taken["stamp"],
                        "skipped": [item["stamp"] for item in newer],
                        "reason": (newer[-1]["problems"] or ["пустой ответ"])[0],
                    })
        chosen = {id(item) for item in latest.values()}
        eligible = [item for item in eligible if id(item) in chosen]

    for item in eligible:
        item["name"] = item["backend"] if not all_runs else f"{item['backend']} ({item['stamp']})"
    return eligible


# --- разбор ответов модели -------------------------------------------------------------

def _strip_trailing_commas(blob: str) -> str:
    """Убирает запятые перед ] и } — но только вне строк JSON."""
    out, in_string, escaped = [], False, False
    for index, char in enumerate(blob):
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            out.append(char)
            continue
        if char == ",":
            rest = blob[index + 1:].lstrip()
            if rest[:1] in ("]", "}") and rest:
                continue
        out.append(char)
    return "".join(out)


def iter_json_objects(text: str):
    """Все JSON-объекты в тексте; `{` внутри строк не ломает разбор (raw_decode)."""
    decoder = json.JSONDecoder()
    index = 0
    while True:
        start = text.find("{", index)
        if start < 0:
            return
        try:
            obj, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            index = start + 1
            continue
        if isinstance(obj, dict):
            yield obj
            index = end
        else:
            index = start + 1


def extract_object(text: str, keys: tuple[str, ...] | str) -> dict | None:
    """Первый объект, содержащий один из ключей. Висячие запятые — вторая попытка."""
    wanted = (keys,) if isinstance(keys, str) else tuple(keys)
    for obj in iter_json_objects(text):
        if any(key in obj for key in wanted):
            return obj
    fixed = _strip_trailing_commas(text)
    if fixed != text:
        for obj in iter_json_objects(fixed):
            if any(key in obj for key in wanted):
                return obj
    return None


# --- колода: страницы, панели, строки --------------------------------------------------

PAGE_HEADING = re.compile(r"^##\s+(?:Слайд|Slide|Страница|Page)\s+(\d+)")
PANEL_HEADING = re.compile(r"^###\s+(.+?)\s*$")


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def markdown(deck: str) -> str:
    path = ROOT / "decks" / deck / f"{deck}.md"
    if not path.is_file():
        raise SystemExit(f"нет колоды: {path}")
    return path.read_text("utf-8")


@lru_cache(maxsize=64)
def _rows_cached(root: str, deck: str) -> tuple:
    found, page, panel = [], None, ""
    for line in markdown(deck).splitlines():
        stripped = line.strip()
        match = PAGE_HEADING.match(stripped)
        if match:
            page, panel = int(match.group(1)), ""
            continue
        match = PANEL_HEADING.match(stripped)
        if match:
            panel = match.group(1)
            continue
        if stripped.startswith("|") and not re.fullmatch(r"\|[\s:\-|]+\|", stripped):
            found.append({"page": page, "panel": panel, "cells": _cells(stripped),
                          "raw": stripped})
    return tuple(found)


def rows(deck: str) -> list[dict]:
    """Строки таблиц с координатами: страница, панель, ячейки. Колода читается один раз."""
    return list(_rows_cached(str(ROOT), deck))


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("ё", "е").replace("Ё", "Е")).strip().lower()


def row_candidates(deck: str, page: int | None, label: str, value: str) -> list[dict]:
    """Все строки колоды, подходящие под факт: та же страница, подпись и целая ячейка значения.

    Кандидатов может быть несколько: на одной странице две панели с одинаковой подписью.
    Решать, какая из них «та», должен не первый попавшийся порядок, а отдельный вызов.
    """
    wanted_label, wanted_value = _norm(label), _norm(value)
    found = []
    for row in rows(deck):
        if page is not None and row["page"] != page:
            continue
        cells = [_norm(cell) for cell in row["cells"]]
        if not cells or cells[0] != wanted_label:
            continue
        if wanted_value and wanted_value not in cells:
            continue
        found.append(row)
    if found:
        return found
    # подпись могла быть обрезана в факте — ищем по вхождению
    for row in rows(deck):
        if page is not None and row["page"] != page:
            continue
        cells = [_norm(cell) for cell in row["cells"]]
        if not cells:
            continue
        if wanted_label[:40] and wanted_label[:40] in cells[0] and \
                (not wanted_value or wanted_value in cells):
            found.append(row)
    return found


def resolve_row(deck: str, page: int | None, label: str, value: str) -> tuple[dict | None, str | None]:
    """Строка факта или причина, почему её нет.

    Неоднозначность (одинаковые подпись и значение в разных панелях одной страницы) — это
    причина «нужно решение человека», а не повод молча связать факт с первой панелью.
    """
    candidates = row_candidates(deck, page, label, value)
    if not candidates:
        return None, "строка не найдена"
    if len(candidates) == 1:
        return candidates[0], None
    panels = sorted({row["panel"] for row in candidates})
    if len(panels) > 1:
        names = ", ".join(panel or "без панели" for panel in panels)
        return None, f"неоднозначно: панели {names}"
    return candidates[0], None


def row_for_fact(deck: str, page: int | None, label: str, value: str) -> dict | None:
    return resolve_row(deck, page, label, value)[0]


def row_index(deck: str) -> dict[str, list[dict]]:
    """Дословная строка таблицы → все строки колоды с таким текстом."""
    index: dict[str, list[dict]] = {}
    for row in rows(deck):
        index.setdefault(row["raw"], []).append(row)
    return index


def is_thematic(text: str, stems: list[str]) -> bool:
    """Тема — по началу слова: «цен» ловит «ценность», но не «процент» и не «оценка»."""
    words = re.findall(r"[a-zа-я0-9]+", _norm(text))
    lowered = [stem.lower() for stem in stems]
    return any(word.startswith(stem) for word in words for stem in lowered)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)
