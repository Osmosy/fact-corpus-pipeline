"""Анализ фактов моделью: выбор значимых фактов и выводы со ссылками на них.

Контракт ответа (строгий JSON, только он идёт в сравнение):
{
  "selected":    [{"fact_id": "F-…", "why": "чем важен"}],
  "conclusions": [{"text": "вывод", "fact_ids": ["F-…"]}],
  "not_relevant":[{"fact_id": "F-…", "why": "почему не значим"}]
}

Приёмка: ответ разбирается, все три списка на месте, каждый fact_id в любом из них есть в
каноне колоды, выводы есть и у каждого вывода есть ссылки. Иначе прогон сохраняется с
непустым `problems` и в сравнение не идёт (см. corpus.load_runs).

Бэкенды:
  zcode   — пул Z.AI через `zcode-start-plan` (тратит пул);
  ollama  — OpenAI-совместимый шлюз к модели (LLM_URL / LLM_MODEL).

Запуск: CORPUS_ROOT=/path/to/project python3 $SKILL/run_analysis.py --backend ollama --deck <колода>
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402

CONTRACT = """Верни ТОЛЬКО JSON без пояснений и без markdown:
{
  "selected": [{"fact_id": "F-…", "why": "чем факт важен для вопроса (до 20 слов)"}],
  "conclusions": [{"text": "вывод (1-2 предложения)", "fact_ids": ["F-…", "F-…"]}],
  "not_relevant": [{"fact_id": "F-…", "why": "почему не значим для вопроса"}]
}
Правила:
- fact_id бери дословно из списка, не выдумывай;
- каждый вывод обязан ссылаться хотя бы на один fact_id;
- не пересказывай все факты: selected — только то, на чём строятся выводы;
- факты, которые ты видел, но не использовал, перечисли в not_relevant с причиной.
"""

KEYS = ("selected", "conclusions")


def build_prompt(deck: str, facts: list[dict], config: dict) -> str:
    lines = [f"{r['fact_id']} | стр.{r['page']} | {r['label']} | {r['value']}" for r in facts]
    return (
        f"Ты {config['role']}. Ниже машиночитаемые факты колоды «{deck}» "
        f"({len(facts)} строк, формат: id | страница | подпись | значение).\n\n"
        f"{config['question']}\n\n"
        + "\n".join(lines)
        + "\n\n"
        + CONTRACT
    )


def call_zcode(prompt: str, keys: tuple[str, ...] = KEYS) -> tuple[str, dict]:
    proc = subprocess.run(
        [corpus.ZCODE_BIN, "-p", prompt, "--cwd", str(corpus.ROOT),
         "--mode", "plan", "--json"],
        capture_output=True, text=True, timeout=1800,
    )
    meta = {"exit": proc.returncode, "stdout_tail": proc.stdout[-300:]}
    # --json печатает конверт {sessionId, response, usage, …}; ответ модели лежит в response.
    envelope = corpus.extract_object(proc.stdout, ("sessionId",))
    answer = None
    if envelope:
        meta["session"] = envelope.get("sessionId")
        meta["usage"] = envelope.get("usage")
        response = envelope.get("response")
        if isinstance(response, dict):
            answer = response
        elif isinstance(response, str):
            answer = corpus.extract_object(response, keys)
    if answer is None:
        answer = corpus.extract_object(proc.stdout, keys)
    meta["answer_found"] = answer is not None
    return json.dumps(answer, ensure_ascii=False) if answer else "", meta


def call_ollama(prompt: str, model: str, keys: tuple[str, ...] = KEYS) -> tuple[str, dict]:
    body = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False,
         "temperature": 0.2},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        corpus.LLM_URL,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer ollama"},
    )
    with urllib.request.urlopen(request, timeout=1800) as response:
        payload = json.loads(response.read().decode("utf-8"))
    text = payload["choices"][0]["message"]["content"]
    meta = {"usage": payload.get("usage"), "model": payload.get("model")}
    answer = corpus.extract_object(text, keys)
    meta["answer_found"] = answer is not None
    return json.dumps(answer, ensure_ascii=False) if answer else "", meta


def _ids(items, field: str) -> list:
    """fact_id или fact_ids из элемента списка; терпит мусор в ответе модели."""
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        value = item.get(field)
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, list):
            out.extend(value)
    return out


def validate(answer: str, facts: list[dict]) -> tuple[dict | None, list[str]]:
    """Проверяет весь ответ, а не только selected: неизвестный id в любом списке — проблема."""
    if not answer:
        return None, ["модель не вернула разбираемый JSON"]
    try:
        data = json.loads(answer)
    except json.JSONDecodeError as error:
        return None, [f"ответ не разбирается как JSON: {error}"]
    if not isinstance(data, dict):
        return None, ["ответ не объект JSON"]

    problems: list[str] = []
    for key in ("selected", "conclusions", "not_relevant"):
        if not isinstance(data.get(key), list):
            problems.append(f"{key}: нет списка")
    if problems:
        return data, problems

    known = {row["fact_id"] for row in facts}
    for key, field in (("selected", "fact_id"), ("conclusions", "fact_ids"),
                       ("not_relevant", "fact_id")):
        unknown = [fid for fid in _ids(data[key], field) if fid not in known]
        if unknown:
            problems.append(f"{key}: несуществующие fact_id {unknown[:5]}")

    conclusions = [item for item in data["conclusions"] if isinstance(item, dict)]
    if not conclusions:
        problems.append("нет выводов")
    for item in conclusions:
        if not item.get("fact_ids"):
            problems.append(f"вывод без ссылок: {str(item.get('text'))[:60]}")
    return data, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("zcode", "ollama"), required=True)
    parser.add_argument("--deck", required=True)
    parser.add_argument("--model", default=corpus.LLM_MODEL)
    parser.add_argument("--thematic-only", action="store_true")
    args = parser.parse_args()

    config = corpus.load_config()
    facts = corpus.load_facts(args.deck)
    if args.thematic_only:
        facts = [row for row in facts if row["thematic"]]
    if not facts:
        print(f"нет фактов для {args.deck}")
        return 2

    prompt = build_prompt(args.deck, facts, config)
    print(f"{args.backend}: {len(facts)} фактов, промпт {len(prompt)} символов")
    started = time.time()
    try:
        answer, meta = (call_zcode(prompt) if args.backend == "zcode"
                        else call_ollama(prompt, args.model))
    except Exception as error:  # noqa: BLE001 — сбой канала не должен терять прогон
        print(f"канал упал: {type(error).__name__}: {error}")
        return 1
    data, problems = validate(answer, facts)

    corpus.RUNS.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = corpus.RUNS / f"{args.deck}.{args.backend}-{stamp}.json"
    corpus.write_json(out, {
        "deck": args.deck,
        "backend": args.backend,
        "facts_total": len(facts),
        "facts_thematic": sum(row["thematic"] for row in facts),
        "seconds": round(time.time() - started, 1),
        "meta": meta,
        "problems": problems,
        "answer": data,
    })
    print(f"→ {corpus.rel(out)}")
    if data:
        print(f"выбрано {len(data.get('selected', []))}, выводов {len(data.get('conclusions', []))}, "
              f"отклонено {len(data.get('not_relevant', []))}")
    for problem in problems:
        print("  проблема:", problem)
    return 0 if data and not problems else 1


if __name__ == "__main__":
    sys.exit(main())
