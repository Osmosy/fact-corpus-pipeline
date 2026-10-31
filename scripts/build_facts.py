"""Факты корпуса → машиночитаемый канон docs/facts/facts.jsonl.

Один факт = одна строка JSON: стабильный id, координаты (колода, страница), подпись,
значение, признак тематической релевантности, хэш колоды. id выводится из содержимого,
поэтому повторная сборка не плодит дубли и не сдвигает нумерацию при добавлении колод.

Факты — не требования: это размеченный материал, из которого модели выбирают важное.
"""
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("CORPUS_ROOT") or Path.cwd()).resolve()
PAGE_FACTS = ROOT / "docs/registry/page_facts.json"
OUT = ROOT / "docs/facts/facts.jsonl"
THEME = (
    "мяс", "колбас", "деликатес", "гастроном", "сосиск", "паштет", "ветчин",
    "полуфабрикат", "покуп", "цен", "упаковк", "вкус", "белок", "состав", "рацион",
    "потребител",
)


def fact_id(deck: str, page: int, label: str, value: str) -> str:
    digest = hashlib.sha256(f"{deck}|{page}|{label}|{value}".encode("utf-8")).hexdigest()
    return "F-" + digest[:12]


def main() -> int:
    if not PAGE_FACTS.is_file():
        raise SystemExit(f"нет {PAGE_FACTS} — атомизация страниц ещё не сделана или указан не тот CORPUS_ROOT")
    data = json.loads(PAGE_FACTS.read_text("utf-8"))["decks"]
    rows = []
    for deck, body in sorted(data.items()):
        for page_raw, page_body in sorted(body["pages"].items(), key=lambda kv: int(kv[0])):
            page = int(page_raw)
            for fact in page_body.get("facts", []):
                label = (fact.get("label") or "").strip()
                value = (fact.get("value") or "").strip()
                if not label or not value:
                    continue
                text = f"{label} {value}".lower()
                rows.append(
                    {
                        "fact_id": fact_id(deck, page, label, value),
                        "deck": deck,
                        "page": page,
                        "label": label,
                        "value": value,
                        "thematic": any(word in text for word in THEME),
                        "deck_sha256": body.get("deck_sha256"),
                    }
                )
    unique = {}
    for row in rows:
        unique.setdefault(row["fact_id"], row)
    rows = sorted(unique.values(), key=lambda r: (r["deck"], r["page"], r["fact_id"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    by_deck: dict[str, int] = {}
    for row in rows:
        by_deck[row["deck"]] = by_deck.get(row["deck"], 0) + 1
    print(f"фактов: {len(rows)} (уникальных id), тематических: {sum(r['thematic'] for r in rows)}")
    for deck, count in sorted(by_deck.items()):
        print(f"  {deck}: {count}")
    print(f"→ {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
