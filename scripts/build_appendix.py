"""Собирает приложение «Справочно» из решений по фактам.

Единственный генератор APPENDIX-INFO.md: и разбор слепых зон (apply_fact_decisions.py),
и правило «рынок РБ → справочно» (rb_to_info.py) пишут решения в fact_decisions.json,
а приложение пересобирается отсюда. Иначе два скрипта дают две разные версии документа.

Запуск: python3 docs/facts/build_appendix.py
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CORPUS_ROOT") or Path.cwd()).resolve()
DECISIONS = ROOT / "docs/facts/fact_decisions.json"
REQUIREMENTS = ROOT / "docs/requirements-registry.jsonl"
SPANS = ROOT / "docs/registry/spans.jsonl"
def appendix_path() -> Path:
    """Где приложение «Справочно»: APPENDIX_INFO, иначе единственное reviews/*/APPENDIX-INFO.md."""
    env = os.environ.get("APPENDIX_INFO")
    if env:
        return ROOT / env
    found = sorted((ROOT / "reviews").glob("*/APPENDIX-INFO.md"))
    return found[0] if found else ROOT / "reviews/APPENDIX-INFO.md"


APPENDIX = None  # вычисляется в main() через appendix_path()


def pages_by_span() -> dict[tuple[str, tuple], int]:
    mapping = {}
    path = SPANS
    if not path.is_file():
        return mapping
    for line in path.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        span = json.loads(line)
        if span.get("page"):
            mapping[(span["file"], tuple(span["span"]))] = span["page"]
    return mapping


def main() -> int:
    if not DECISIONS.is_file():
        print("нет fact_decisions.json")
        return 2
    decisions = json.loads(DECISIONS.read_text("utf-8"))

    req_texts, req_pages = {}, {}
    spans = pages_by_span()
    for line in REQUIREMENTS.read_text("utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            req_texts[record["req_id"]] = record.get("raw_text", "").strip()
            key = (record["source"]["file"], tuple(record["source"]["span"]))
            req_pages[record["req_id"]] = spans.get(key)

    rows = []
    for fid, decision in decisions.items():
        if decision.get("target") != "info":
            continue
        req_id = decision.get("req_id")
        raw = req_texts.get(req_id or "", "")
        if raw:
            cells = [cell.strip() for cell in raw.strip("|").split("|")]
            label = cells[0]
            value = " / ".join(cell for cell in cells[1:] if cell)
        else:
            label, value = decision.get("label", ""), decision.get("value", "")
        page = decision.get("page") or req_pages.get(req_id or "")
        rows.append((decision.get("deck", ""), page, label, value or decision.get("value", ""),
                     decision.get("reason", "")))

    lines = [
        "# Справочно",
        "",
        "Факты, отмеченные как информация, а не как опора выводов. Решение и причина указаны",
        "у каждого: факт не обязан попадать в выводы, но обязан быть виден.",
        "",
        "| колода | стр. | факт | значение | причина |",
        "|---|---|---|---|---|",
    ]
    for deck, page, label, value, reason in sorted(rows, key=lambda r: (r[0], r[1] or 0)):
        lines.append(f"| {deck} | {page if page else '—'} | {label} | {value} | {reason} |")
    APPENDIX = appendix_path()
    APPENDIX.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"справочно: {len(rows)} фактов → {APPENDIX.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
