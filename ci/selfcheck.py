#!/usr/bin/env python3
"""Самопроверка репозитория: то, что не ловят тесты.

Проверяет: скрипты компилируются, оболочка цела, ссылки в README и SKILL.md не битые,
у SKILL.md валидный frontmatter и канонический раздел с граблями, в докстрингах нет
устаревших путей `docs/facts/*.py`, в файлах нет секретов, копия dispositions.py в проекте
не разошлась с репозиторием (если проект указан).

Код выхода 0 — чисто, 1 — есть находки.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SECRETS = (
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)

STALE_PATH = re.compile(r"docs/(?:facts|registry/tools)/[A-Za-z0-9_\-]+\.py")

problems: list[str] = []


def check_compile() -> None:
    for path in sorted(ROOT.glob("scripts/*.py")) + sorted(ROOT.glob("tests/*.py")) + \
            sorted(ROOT.glob("ci/*.py")):
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            problems.append(f"{path.relative_to(ROOT)}: синтаксис — {exc}")


def check_shell() -> None:
    for name in ("scripts/run_all.sh", "ci/watch.sh"):
        script = ROOT / name
        if not script.is_file():
            continue
        done = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        if done.returncode != 0:
            problems.append(f"{name}: {done.stderr.strip()}")


def _links(text: str, where: str) -> None:
    for name in sorted(set(re.findall(r"scripts/([A-Za-z0-9_\-]+\.(?:py|sh))", text))):
        if not (ROOT / "scripts" / name).is_file():
            problems.append(f"{where} ссылается на scripts/{name}, файла нет")
    for name in sorted(set(re.findall(r"docs/([A-Za-z0-9_\-]+\.md)", text))):
        if not (ROOT / "docs" / name).is_file():
            problems.append(f"{where} ссылается на docs/{name}, файла нет")


def check_docs() -> None:
    for name in ("README.md", "SKILL.md"):
        path = ROOT / name
        if not path.is_file():
            problems.append(f"нет {name}")
            continue
        _links(path.read_text(encoding="utf-8"), name)


def check_stale_paths() -> None:
    for path in sorted(ROOT.glob("scripts/*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not STALE_PATH.search(line):
                continue
            if line.lstrip().startswith(("Запуск", "python3", "…")):
                problems.append(f"{path.relative_to(ROOT)}:{number}: устаревший путь запуска — "
                                "используй CORPUS_ROOT=… python3 $SKILL/<скрипт>")


def check_skill() -> None:
    path = ROOT / "SKILL.md"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        problems.append("SKILL.md: нет frontmatter")
        return
    head = text.split("---", 2)[1]
    fields = dict(
        line.split(":", 1) for line in head.strip().splitlines() if ":" in line and not line.startswith(" ")
    )
    for required in ("name", "description"):
        if required not in fields:
            problems.append(f"SKILL.md: нет поля {required}")
    description = fields.get("description", "").strip()
    if description and len(description) > 60:
        problems.append(f"SKILL.md: description {len(description)} символов, максимум 60")
    if "## Common Pitfalls" not in text:
        problems.append("SKILL.md: нет канонического раздела ## Common Pitfalls")


def check_secrets() -> None:
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        if path.suffix not in {".py", ".sh", ".md", ".json", ".yml", ".yaml", ""}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            problems.append(f"{path.relative_to(ROOT)}: не читается — {exc}")
            continue
        for pattern in SECRETS:
            if pattern.search(text):
                problems.append(f"{path.relative_to(ROOT)}: похоже на секрет ({pattern.pattern[:16]}…)")


def check_dispositions_copy() -> None:
    """В проекте есть своя копия dispositions.py (её импортирует предикат) — сверяем хэш."""
    corpus_root = os.environ.get("CORPUS_ROOT")
    if not corpus_root:
        return
    project = Path(corpus_root) / "docs/registry/tools/dispositions.py"
    if not project.is_file():
        return
    ours = hashlib.sha256((ROOT / "scripts/dispositions.py").read_bytes()).hexdigest()
    theirs = hashlib.sha256(project.read_bytes()).hexdigest()
    if ours != theirs:
        problems.append(f"dispositions.py в проекте ({project}) разошёлся с репозиторием")


def check_numbers() -> list[str]:
    """Числа в документах сверяются со снимком отчёта — та самая ошибка 43/41 и 76/78."""
    import subprocess
    done = subprocess.run([sys.executable, str(ROOT / "ci/numbers.py"), "--quiet"],
                          capture_output=True, text=True)
    if done.returncode != 0:
        return [f"числа в документах расходятся с отчётом: "
                f"{(done.stdout + done.stderr).strip().splitlines()[:3]}"]
    return []


def main() -> int:
    check_compile()
    check_shell()
    check_docs()
    check_stale_paths()
    check_skill()
    check_secrets()
    check_dispositions_copy()
    if problems:
        print(f"найдено проблем: {len(problems)}")
        for item in problems:
            print(" ", item)
        return 1
    print("самопроверка: чисто")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
