"""Собирает приложение «Справочно» из решений по фактам.

Единственный генератор APPENDIX-INFO.md: и разбор слепых зон, и правило «второстепенный
рынок → справочно» пишут решения в fact_decisions.json, а приложение пересобирается здесь.
Иначе два скрипта дают две разные версии документа.

Работает и без реестра требований: если docs/requirements-registry.jsonl нет, подпись и
значение берутся из самого решения. Если приложений несколько и не задан APPENDIX_INFO —
скрипт останавливается: молча выбрать одно значит потерять остальные.

Запуск: CORPUS_ROOT=/path/to/project python3 $SKILL/build_appendix.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402


def appendix_path() -> Path:
    """Где приложение: APPENDIX_INFO, иначе единственное reviews/*/APPENDIX-INFO.md."""
    env = os.environ.get("APPENDIX_INFO")
    if env:
        return corpus.ROOT / env
    found = sorted((corpus.ROOT / "reviews").glob("*/APPENDIX-INFO.md")) if \
        (corpus.ROOT / "reviews").is_dir() else []
    if len(found) > 1:
        raise SystemExit(
            "найдено несколько приложений, укажи нужное:\n  "
            + "\n  ".join(corpus.rel(path) for path in found)
            + "\nпеременной APPENDIX_INFO=<путь относительно корня>"
        )
    return found[0] if found else corpus.ROOT / "reviews/APPENDIX-INFO.md"


def pages_by_span() -> dict[tuple[str, tuple], int]:
    mapping = {}
    spans_path = corpus.ROOT / "docs/registry/spans.jsonl"
    for span in corpus.load_jsonl(spans_path):
        if span.get("page"):
            mapping[(span["file"], tuple(span["span"]))] = span["page"]
    return mapping


def cell(text: str) -> str:
    """Значение для markdown-таблицы: вертикальная черта ломает строку."""
    return (text or "—").replace("|", "/").replace("\n", " ").strip() or "—"


def main() -> int:
    if not corpus.DECISIONS.is_file():
        print(f"нет {corpus.rel(corpus.DECISIONS)} — сначала apply_fact_decisions.py")
        return 2
    decisions = json.loads(corpus.DECISIONS.read_text("utf-8"))

    req_texts, req_pages = {}, {}
    spans = pages_by_span()
    for record in corpus.load_jsonl(corpus.REQUIREMENTS):
        req_texts[record["req_id"]] = record.get("raw_text", "").strip()
        if record.get("source"):
            key = (record["source"]["file"], tuple(record["source"]["span"]))
            req_pages[record["req_id"]] = spans.get(key)

    rows = []
    for fid, decision in decisions.items():
        if decision.get("target") != "info":
            continue
        req_id = decision.get("req_id") or ""
        raw = req_texts.get(req_id, "")
        if raw:
            cells = [part.strip() for part in raw.strip("|").split("|")]
            label = cells[0]
            value = " / ".join(part for part in cells[1:] if part)
        else:
            label, value = decision.get("label", ""), decision.get("value", "")
        page = decision.get("page") or req_pages.get(req_id)
        rows.append((decision.get("deck", ""), page, label, value or decision.get("value", ""),
                     decision.get("reason", ""), fid))

    lines = [
        "# Справочно",
        "",
        "Факты, отмеченные как информация, а не как опора выводов. Решение и причина указаны",
        "у каждого: факт не обязан попадать в выводы, но обязан быть виден.",
        "",
        "| колода | стр. | факт | значение | причина |",
        "|---|---|---|---|---|",
    ]
    for deck, page, label, value, reason, fid in sorted(rows, key=lambda r: (r[0], r[1] or 0)):
        lines.append(f"| {cell(deck)} | {page if page else '—'} | {cell(label)} | "
                     f"{cell(value)} | {cell(reason)} |")

    owner = corpus.load_owner_facts()
    if owner:
        lines += ["", "## Знание владельца", "",
                  "Сведения, которых нет в колодах. Источник и дата указаны у каждого:", ""]
        for row in owner:
            lines.append(f"- **{row['fact_id']}** — {row.get('statement')}")
            lines.append(f"  источник: {row.get('source')}, {row.get('date')}, "
                         f"область: {row.get('scope', '—')}")
        lines.append("")

    path = appendix_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    info_total = sum(1 for decision in decisions.values() if decision.get("target") == "info")
    print(f"справочно: {len(rows)} фактов → {corpus.rel(path)}")
    if len(rows) != info_total:
        print(f"  расхождение: решений «info» {info_total}, строк в приложении {len(rows)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())