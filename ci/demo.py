#!/usr/bin/env python3
"""Демо-корпус проходит офлайн и даёт те же числа, что в docs/demo.md.

Копирует examples/demo-corpus во временный каталог, прогоняет весь конвейер без сети
(ответы моделей уже лежат в runs/), собирает REPORT.json и сравнивает его с эталоном
docs/demo-expected.report.json. Расхождение — находка.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
DEMO = ROOT / "examples/demo-corpus"
EXPECTED = ROOT / "docs/demo-expected.report.json"
STEPS = (("validate_input.py",), ("build_facts.py",),
         ("compare_analyses.py", "demo-produkty-2026"),
         ("compare_analyses.py", "demo-upakovka-2026"),
         ("blind_spots.py",), ("cost_report.py",), ("report.py",))


def main() -> int:
    if not EXPECTED.is_file():
        print(f"нет эталона {EXPECTED.relative_to(ROOT)}")
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="fcp-demo-"))
    problems: list[str] = []
    try:
        shutil.copytree(DEMO, tmp, dirs_exist_ok=True)
        env = {**__import__("os").environ, "CORPUS_ROOT": str(tmp)}
        env.pop("APPENDIX_INFO", None)
        for step in STEPS:
            done = subprocess.run([sys.executable, str(SCRIPTS / step[0]), *step[1:]],
                                  capture_output=True, text=True, env=env)
            # validate_input возвращает 1 только на ошибках входа; в демо их нет
            if done.returncode != 0 and step[0] != "validate_input.py":
                problems.append(f"{step[0]} {step[1:]} → код {done.returncode}: "
                                f"{(done.stdout + done.stderr).strip()[-200:]}")
        report = json.loads((tmp / "docs/facts/REPORT.json").read_text("utf-8"))
        expected = json.loads(EXPECTED.read_text("utf-8"))
        for key, value in expected.items():
            if isinstance(value, (dict, list)):
                continue
            if report.get(key) != value:
                problems.append(f"{key}: в демо {report.get(key)}, в эталоне {value}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    for item in problems:
        print("ошибка:", item)
    print(f"демо: шагов {len(STEPS)}, расхождений {len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
