#!/usr/bin/env python3
"""Самопроверка репозитория: то, что нельзя проверить тестами, проверяется этим скриптом.

Проверяет: скрипты компилируются, оболочка синтаксически цела, README не ссылается на
несуществующие файлы, SKILL.md имеет валидный frontmatter, в репозитории нет секретов.
Код выхода 0 — чисто, 1 — есть находки.
"""

from __future__ import annotations

import ast
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

problems: list[str] = []


def check_compile() -> None:
    for path in sorted(ROOT.glob("scripts/*.py")):
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            problems.append(f"{path.relative_to(ROOT)}: синтаксис — {exc}")


def check_shell() -> None:
    script = ROOT / "scripts/run_all.sh"
    if not script.is_file():
        problems.append("нет scripts/run_all.sh")
        return
    done = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    if done.returncode != 0:
        problems.append(f"run_all.sh: {done.stderr.strip()}")


def check_readme() -> None:
    readme = ROOT / "README.md"
    if not readme.is_file():
        problems.append("нет README.md")
        return
    text = readme.read_text(encoding="utf-8")
    for name in sorted(set(re.findall(r"scripts/([A-Za-z0-9_\-]+\.(?:py|sh))", text))):
        if not (ROOT / "scripts" / name).is_file():
            problems.append(f"README ссылается на scripts/{name}, файла нет")
    for name in sorted(set(re.findall(r"docs/([A-Za-z0-9_\-]+\.md)", text))):
        if not (ROOT / "docs" / name).is_file():
            problems.append(f"README ссылается на docs/{name}, файла нет")


def check_skill() -> None:
    path = ROOT / "SKILL.md"
    if not path.is_file():
        problems.append("нет SKILL.md")
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


def main() -> int:
    check_compile()
    check_shell()
    check_readme()
    check_skill()
    check_secrets()
    if problems:
        print(f"найдено проблем: {len(problems)}")
        for item in problems:
            print(" ", item)
        return 1
    print("самопроверка: чисто")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
