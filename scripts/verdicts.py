#!/usr/bin/env python3
"""Вердикты по фактам: общий механизм для слепых зон и разбора «выбрал один».

Один контракт: модель отвечает `{"verdicts": [{"fact_id", "verdict", "why"}]}`, где verdict —
`material` (важно для вопроса), `background` (фон, методология, детали теста) или
`irrelevant` (не к вопросу). Сводка считается по факту: «все материал», «разошлись»,
«все фон», «ответили не все».

Модуль ничего не решает сам: он строит промпт, разбирает ответ и сводит группы.
"""
from __future__ import annotations

import json

VERDICTS = ("material", "background", "irrelevant")
CONTRACT = """Верни ТОЛЬКО JSON:
{"verdicts": [{"fact_id": "F-…", "verdict": "material|background|irrelevant",
               "why": "почему (до 15 слов)"}]}
Правила:
- fact_id бери дословно из списка, не выдумывай;
- material — факт нужен для ответа на вопрос;
- background — методология, выборка, структура отчёта, нишевые детали;
- irrelevant — не про вопрос вовсе;
- у каждого факта из списка должен быть вердикт.
"""


def build_prompt(deck: str, rows: list[dict], config: dict, task: str) -> str:
    lines = [f"{row['fact_id']} | стр.{row['page']} | {row['label']} | {row['value']}"
             for row in rows]
    return (f"Ты {config['role']}. {task}\n\n{config['question']}\n\n"
            "Факты (id | страница | подпись | значение):\n" + "\n".join(lines) + "\n\n" + CONTRACT)


def parse(answer: str) -> tuple[dict[str, dict], list[str]]:
    """Ответ → вердикты по id и список проблем (мусор, неверные коды, пропуски)."""
    if not answer:
        return {}, ["модель не вернула разбираемый JSON"]
    try:
        body = json.loads(answer)
    except json.JSONDecodeError as error:
        return {}, [f"ответ не разбирается как JSON: {error}"]
    items = body.get("verdicts") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return {}, ["нет списка verdicts"]

    verdicts: dict[str, dict] = {}
    problems: list[str] = []
    for item in items:
        if not isinstance(item, dict) or not item.get("fact_id"):
            problems.append(f"строка без fact_id: {str(item)[:60]}")
            continue
        verdict = item.get("verdict")
        if verdict not in VERDICTS:
            problems.append(f"{item['fact_id']}: неизвестный вердикт {verdict!r}")
            continue
        verdicts[item["fact_id"]] = {"fact_id": item["fact_id"], "verdict": verdict,
                                     "why": str(item.get("why") or "")[:300]}
    return verdicts, problems


def summary(verdicts_by_channel: dict[str, dict[str, dict]], expected: list[str]) -> dict:
    """Сводка по факту, а не по модели: иначе «все считают материалом» врёт в пользу того, кто успел."""
    groups = {"all_material": [], "split": [], "all_background": [], "not_all_answered": []}
    for fact_id in expected:
        answers = [verdicts_by_channel[channel].get(fact_id) for channel in verdicts_by_channel]
        codes = [answer["verdict"] for answer in answers if answer]
        if len(codes) < len(verdicts_by_channel):
            groups["not_all_answered"].append(fact_id)
        elif set(codes) == {"material"}:
            groups["all_material"].append(fact_id)
        elif len(set(codes)) == 1:
            groups["all_background"].append(fact_id)
        else:
            groups["split"].append(fact_id)
    return groups
