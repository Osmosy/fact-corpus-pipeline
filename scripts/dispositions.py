"""Диспозиции обязательств: куда идёт факт и почему.

Файл `docs/registry/dispositions.json` заполняет человек (или агент по его решению):
{
  "REQ-0007": {"target": "conclusions", "reason": "ключевой факт категории", "by": "аналитик"},
  "REQ-0025": {"target": "info", "reason": "фон по брендам", "by": "аналитик"},
  "REQ-0031": {"target": "waive", "reason": "уровень жизни, к вопросу не относится", "by": "аналитик"}
}

`conclusions` — факт обязан быть в выводах (проверяется по AGENT-REVIEW и материалам агентов).
`info` — факт идёт в приложении «Справочно», в выводы не обязан (проверяется только там).
`waive` — обязательство снимается, требование переводится в rejected с причиной.
"""
import json
from pathlib import Path

DISPOSITIONS = Path("docs/registry/dispositions.json")

TARGETS = ("conclusions", "info", "waive")


def load(root: Path) -> dict[str, dict]:
    path = root / DISPOSITIONS
    if not path.is_file():
        return {}
    data = json.loads(path.read_text("utf-8"))
    out = {}
    for req_id, entry in data.items():
        if not isinstance(entry, dict):
            continue
        target = entry.get("target")
        if target not in TARGETS:
            raise ValueError(f"{req_id}: target вне {TARGETS}: {target!r}")
        out[req_id] = entry
    return out


def target_of(root: Path, req_id: str) -> str:
    """Решение по требованию; по умолчанию факт обязан быть в выводах."""
    entry = load(root).get(req_id)
    return entry["target"] if entry else "conclusions"
