"""Анализ фактов моделью: выбор значимых фактов и выводы со ссылками на них.

Контракт ответа (строгий JSON, только он идёт в сравнение):
{
  "selected":    [{"fact_id": "F-…", "why": "чем важен"}],
  "conclusions": [{"text": "вывод", "fact_ids": ["F-…"]}],
  "not_relevant":[{"fact_id": "F-…", "why": "почему не значим"}]
}

Бэкенды:
  zcode   — промо-пул Z.AI через `zcode-start-plan` (GLM-5.3-Flash), тратит пул;
  ollama  — локальный шлюз к облачной модели, OpenAI-совместимый /v1.

Запуск: python3 docs/facts/run_analysis.py --backend zcode --deck inkofood-2026
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("CORPUS_ROOT") or Path.cwd()).resolve()
FACTS = ROOT / "docs/facts/facts.jsonl"
RUNS = ROOT / "docs/facts/runs"

QUESTION = (
    "Вопрос исследования: что определяет покупку мясной гастрономии (колбасы, деликатесы, "
    "ветчина, цельномясные продукты) и где лежат возможности роста для бренда."
)

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


def load_facts(deck: str | None) -> list[dict]:
    rows = []
    for line in FACTS.read_text("utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if deck is None or row["deck"] == deck:
                rows.append(row)
    return rows


def build_prompt(deck: str, facts: list[dict]) -> str:
    lines = [f"{r['fact_id']} | стр.{r['page']} | {r['label']} | {r['value']}" for r in facts]
    return (
        f"Ты аналитик рынка FMCG. Ниже машиночитаемые факты колоды «{deck}» "
        f"({len(facts)} строк, формат: id | страница | подпись | значение).\n\n"
        f"{QUESTION}\n\n"
        + "\n".join(lines)
        + "\n\n"
        + CONTRACT
    )


def extract_object(text: str, must_have: str) -> dict | None:
    """Ищет в тексте первый сбалансированный JSON-объект, содержащий ключ must_have."""
    for start, char in enumerate(text):
        if char != "{":
            continue
        depth = 0
        for index in range(start, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    blob = text[start : index + 1]
                    if must_have in blob:
                        blob = re.sub(r",\s*([\]}])", r"\1", blob)
                        try:
                            return json.loads(blob)
                        except json.JSONDecodeError:
                            break
                    break
    return None


def call_zcode(prompt: str, keys: tuple[str, ...] = ("selected", "conclusions")) -> tuple[str, dict]:
    proc = subprocess.run(
        [str(Path.home() / ".local/bin/zcode-start-plan"), "-p", prompt, "--cwd", str(ROOT),
         "--mode", "plan", "--json"],
        capture_output=True, text=True, timeout=1800,
    )
    meta = {"exit": proc.returncode, "stdout_tail": proc.stdout[-300:]}
    # --json печатает конверт {sessionId, response, usage, …}; ответ модели лежит в response.
    envelope = None
    for start, char in enumerate(proc.stdout):
        if char != "{":
            continue
        depth = 0
        for index in range(start, len(proc.stdout)):
            if proc.stdout[index] == "{":
                depth += 1
            elif proc.stdout[index] == "}":
                depth -= 1
                if depth == 0:
                    blob = re.sub(r",\s*([\]}])", r"\1", proc.stdout[start : index + 1])
                    try:
                        candidate = json.loads(blob)
                    except json.JSONDecodeError:
                        break
                    if "sessionId" in candidate:
                        envelope = candidate
                    break
        if envelope:
            break
    answer = None
    if envelope:
        meta["session"] = envelope.get("sessionId")
        meta["usage"] = envelope.get("usage")
        response = envelope.get("response")
        if isinstance(response, dict):
            answer = response
        elif isinstance(response, str):
            answer = next((found for key in keys if (found := extract_object(response, key))), None)
    if answer is None:
        answer = next((found for key in keys if (found := extract_object(proc.stdout, key))), None)
    meta["answer_found"] = answer is not None
    return json.dumps(answer, ensure_ascii=False) if answer else "", meta


def call_ollama(prompt: str, model: str, keys: tuple[str, ...] = ("selected", "conclusions")) -> tuple[str, dict]:
    body = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False,
         "temperature": 0.2},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        "http://127.0.0.1:11434/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer ollama"},
    )
    with urllib.request.urlopen(request, timeout=1800) as response:
        payload = json.loads(response.read().decode("utf-8"))
    text = payload["choices"][0]["message"]["content"]
    meta = {"usage": payload.get("usage"), "model": payload.get("model")}
    answer = next((found for key in keys if (found := extract_object(text, key))), None)
    meta["answer_found"] = answer is not None
    return json.dumps(answer, ensure_ascii=False) if answer else "", meta


def validate(answer: str, facts: list[dict]) -> tuple[dict | None, list[str]]:
    problems: list[str] = []
    if not answer:
        return None, ["модель не вернула разбираемый JSON"]
    data = json.loads(answer)
    known = {row["fact_id"] for row in facts}
    selected = [item for item in data.get("selected", []) if isinstance(item, dict)]
    conclusions = [item for item in data.get("conclusions", []) if isinstance(item, dict)]
    bad = [item.get("fact_id") for item in selected if item.get("fact_id") not in known]
    if bad:
        problems.append(f"несуществующие fact_id: {bad[:5]}")
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
    parser.add_argument("--model", default="deepseek-v4.1-flash:cloud")
    parser.add_argument("--thematic-only", action="store_true")
    args = parser.parse_args()

    facts = load_facts(args.deck)
    if args.thematic_only:
        facts = [row for row in facts if row["thematic"]]
    if not facts:
        print(f"нет фактов для {args.deck}")
        return 2

    prompt = build_prompt(args.deck, facts)
    print(f"{args.backend}: {len(facts)} фактов, промпт {len(prompt)} символов")
    started = time.time()
    try:
        answer, meta = (call_zcode(prompt) if args.backend == "zcode"
                        else call_ollama(prompt, args.model))
    except Exception as error:  # noqa: BLE001 — сбой канала не должен терять прогон
        print(f"канал упал: {type(error).__name__}: {error}")
        return 1
    data, problems = validate(answer, facts)

    RUNS.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = RUNS / f"{args.deck}.{args.backend}-{stamp}.json"
    out.write_text(
        json.dumps(
            {
                "deck": args.deck,
                "backend": args.backend,
                "facts_total": len(facts),
                "facts_thematic": sum(row["thematic"] for row in facts),
                "seconds": round(time.time() - started, 1),
                "meta": meta,
                "problems": problems,
                "answer": data,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"→ {out.relative_to(ROOT)}")
    if data:
        print(f"выбрано {len(data.get('selected', []))}, выводов {len(data.get('conclusions', []))}, "
              f"отклонено {len(data.get('not_relevant', []))}")
    for problem in problems:
        print("  проблема:", problem)
    return 0 if data and not problems else 1


if __name__ == "__main__":
    sys.exit(main())
