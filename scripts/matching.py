#!/usr/bin/env python3
"""Сверка «факт упомянут в выводах» по основам слов, а не по дословной подписи.

Зачем: пересказ («больше мяса» вместо «высокое содержание мяса») давал ложный провал,
хотя факт в выводах есть. Дословная сверка при этом не ослабляется: совпадение считается
только если доля основ значимых слов подписи в одном предложении не ниже порога и, когда
у факта есть число, это число стоит в том же предложении.

Порог и стоп-слова — данные корпуса (`match.min_share`, `match.stopwords` в config.json).

Запуск как библиотеки:
    import matching
    result = matching.match(label, value, text, min_share=0.6, stopwords=[...])
    result["matched"], result["sentence"], result["found"], result["missing"]
"""
from __future__ import annotations

import re

try:                                    # первая внешняя зависимость проекта
    import snowballstemmer
except ModuleNotFoundError:             # pragma: no cover - проверяется в CI отдельно
    raise SystemExit(
        "нужен пакет snowballstemmer (основы русских слов): "
        "pip install -r requirements.txt"
    )

STEMMER = snowballstemmer.stemmer("russian")
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n{2,}")
WORD = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+")
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
DEFAULT_STOPWORDS = (
    "и", "в", "во", "на", "с", "со", "по", "для", "из", "от", "до", "к", "ко", "о", "об",
    "не", "ни", "что", "как", "это", "при", "или", "а", "но", "у", "же", "бы", "за",
    "более", "менее", "также", "только", "если", "то", "их", "его", "её", "все", "весь",
    "который", "которая", "которые", "быть", "есть", "был", "была", "были", "может",
)


def normalize(text: str) -> str:
    return str(text).lower().replace("ё", "е")


def words(text: str) -> list[str]:
    return WORD.findall(normalize(text))


def stems(text: str, stopwords: tuple[str, ...] | list[str] = DEFAULT_STOPWORDS) -> list[str]:
    """Основы значимых слов в порядке появления, без повторов."""
    stop = {normalize(word) for word in stopwords}
    seen: list[str] = []
    for word in words(text):
        if word in stop or word.isdigit():
            continue
        stem = STEMMER.stemWord(word)
        if len(stem) < 3 or stem in seen:
            continue
        seen.append(stem)
    return seen


def numbers(text: str) -> set[str]:
    """Числа в сравнимом виде: «54,8 %» и «54.8%» — одно и то же."""
    return {value.replace(",", ".") for value in NUMBER.findall(normalize(text))}


def match(label: str, value: str, text: str, min_share: float = 0.6,
          stopwords: tuple[str, ...] | list[str] = DEFAULT_STOPWORDS) -> dict:
    """Есть ли факт в тексте: доля основ подписи в одном предложении + совпадение числа."""
    label_stems = stems(label, stopwords)
    value_stems = stems(value, stopwords) if not numbers(value) else []
    wanted = label_stems + [stem for stem in value_stems if stem not in label_stems]
    fact_numbers = numbers(value)

    best = {"matched": False, "sentence": "", "found": [], "missing": list(wanted),
            "share": 0.0, "number_found": False}
    if not wanted:
        return best

    for raw in SENTENCE.split(text or ""):
        sentence = raw.strip()
        if not sentence:
            continue
        have = set(stems(sentence, stopwords))
        found = [stem for stem in wanted if stem in have]
        missing = [stem for stem in wanted if stem not in have]
        share = len(found) / len(wanted)
        number_found = (not fact_numbers) or bool(fact_numbers & numbers(sentence))
        ok = share >= min_share and number_found
        if ok:
            return {"matched": True, "sentence": sentence, "found": found, "missing": missing,
                    "share": round(share, 2), "number_found": number_found}
        if (share, number_found) > (best["share"], best["number_found"]):
            best = {"matched": False, "sentence": sentence, "found": found, "missing": missing,
                    "share": round(share, 2), "number_found": number_found}
    return best
