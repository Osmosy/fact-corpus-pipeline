"""Атомизация страниц → машиночитаемый канон docs/facts/facts.jsonl.

Вход: docs/registry/page_facts.json (что извлечено из страниц колод).
Выход: docs/facts/facts.jsonl и журнал отклонённых docs/facts/facts-rejected.jsonl.

Один факт = одна строка JSON: стабильный id, координаты, подпись, значение, признак темы,
хэш колоды. id выводится из содержимого, поэтому пересборка не сдвигает номера и не плодит
дублей при добавлении колод.

Качество входа проверяется здесь же:
  - факт без `verified: true` в канон не идёт, а попадает в журнал отклонённых с причиной;
  - факт без подписи или значения — тоже в журнал;
  - дубли (deck, page, label, value) считаются и печатаются, а не выбрасываются молча;
  - с флагом `--strict` факты с ошибками входного контроля (значение не на своей странице,
    подпись не найдена дословно) не идут в канон: причиной в журнале становится код
    находки из `docs/facts/INPUT-CHECK.json`.

Запуск: CORPUS_ROOT=/path/to/project python3 $SKILL/build_facts.py [--strict]
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402


def fact_id(deck: str, page: int, label: str, value: str) -> str:
    digest = hashlib.sha256(f"{deck}|{page}|{label}|{value}".encode("utf-8")).hexdigest()
    return "F-" + digest[:12]


INPUT_CHECK = corpus.ROOT / "docs/facts/INPUT-CHECK.json"


def strict_errors() -> dict[tuple, str]:
    """Факты с ошибками входа: (колода, страница, подпись, значение) → код находки."""
    if not INPUT_CHECK.is_file():
        raise SystemExit(
            f"--strict требует {corpus.rel(INPUT_CHECK)} — сначала запусти validate_input.py")
    report = json.loads(INPUT_CHECK.read_text("utf-8"))
    blocked: dict[tuple, str] = {}
    for body in report.get("decks", {}).values():
        for finding in body.get("findings", []):
            if finding.get("level") != "error":
                continue
            key = (body["deck"], finding.get("page"), (finding.get("label") or "").strip(),
                   (finding.get("value") or "").strip())
            blocked[key] = finding["code"]
    return blocked


def main() -> int:
    strict = "--strict" in sys.argv[1:]
    config = corpus.load_config(required=("theme_stems",))
    blocked = strict_errors() if strict else {}
    if not corpus.PAGE_FACTS.is_file():
        raise SystemExit(
            f"нет {corpus.PAGE_FACTS} — атомизация страниц ещё не сделана "
            "или указан не тот CORPUS_ROOT"
        )
    data = json.loads(corpus.PAGE_FACTS.read_text("utf-8"))["decks"]

    rows, rejected, duplicates = [], [], 0
    seen: set[str] = set()
    for deck, body in sorted(data.items()):
        for page_raw, page_body in sorted(body["pages"].items(), key=lambda kv: int(kv[0])):
            page = int(page_raw)
            for fact in page_body.get("facts", []):
                label = (fact.get("label") or "").strip()
                value = (fact.get("value") or "").strip()
                where = {"deck": deck, "page": page, "label": label, "value": value}
                if not label or not value:
                    rejected.append({**where, "reason": "пустая подпись или значение"})
                    continue
                code = blocked.get((deck, page, label, value))
                if code:
                    rejected.append({**where, "reason": f"входной контроль: {code}"})
                    continue
                if fact.get("verified") is not True:
                    rejected.append({**where, "reason": "нет verified: true (факт не сверен с источником)"})
                    continue
                identifier = fact_id(deck, page, label, value)
                if identifier in seen:
                    duplicates += 1
                    continue
                seen.add(identifier)
                rows.append({
                    "fact_id": identifier,
                    "deck": deck,
                    "page": page,
                    "label": label,
                    "value": value,
                    "thematic": corpus.is_thematic(f"{label} {value}", config["theme_stems"]),
                    "deck_sha256": body.get("deck_sha256"),
                })

    rows.sort(key=lambda r: (r["deck"], r["page"], r["fact_id"]))
    corpus.FACTS.parent.mkdir(parents=True, exist_ok=True)
    corpus.FACTS.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")

    if rejected:
        corpus.REJECTED_FACTS.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rejected) + "\n", encoding="utf-8")
    elif corpus.REJECTED_FACTS.is_file():
        corpus.REJECTED_FACTS.unlink()

    by_deck: dict[str, int] = {}
    for row in rows:
        by_deck[row["deck"]] = by_deck.get(row["deck"], 0) + 1
    print(f"фактов: {len(rows)} (уникальных id), тематических: {sum(r['thematic'] for r in rows)}, "
          f"дублей: {duplicates}, отклонено: {len(rejected)}"
          + (f", из них входным контролем {sum(1 for r in rejected if str(r['reason']).startswith('входной'))}"
             if strict else ""))
    for deck, count in sorted(by_deck.items()):
        print(f"  {deck}: {count}")
    if rejected:
        print(f"журнал отклонённых: {corpus.rel(corpus.REJECTED_FACTS)}")
    print(f"→ {corpus.rel(corpus.FACTS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
