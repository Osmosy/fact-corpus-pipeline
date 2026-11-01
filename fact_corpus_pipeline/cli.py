"""Команда `fcp <шаг>`: тонкая обёртка над scripts/*.py.

Скрипты не переписываются в пакет: они и есть контракт (`$SKILL/<скрипт>.py`, вызовы из
Hermes и из документации). Обёртка ищет каталог скриптов и запускает нужный шаг с теми же
аргументами: `fcp facts --strict`, `fcp analyze --backend zcode --deck romir-trendy-2026`.

Где ищутся скрипты: переменная `FCP_SCRIPTS`, затем `scripts/` рядом с клоном репозитория,
затем `./scripts` в текущем каталоге.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

STEPS = {
    "check-input": "validate_input.py",
    "facts": "build_facts.py",
    "analyze": "run_analysis.py",
    "compare": "compare_analyses.py",
    "summary": "summary_all.py",
    "blind": "blind_spots.py",
    "single": "single_pick.py",
    "theme": "theme_audit.py",
    "stability": "stability.py",
    "decisions": "apply_fact_decisions.py",
    "appendix": "build_appendix.py",
    "dispositions": "apply_dispositions.py",
    "rb": "rb_to_info.py",
    "report": "report.py",
    "cost": "cost_report.py",
}


def scripts_dir() -> Path:
    candidates = []
    if os.environ.get("FCP_SCRIPTS"):
        candidates.append(Path(os.environ["FCP_SCRIPTS"]))
    here = Path(__file__).resolve().parent
    candidates += [here.parent / "scripts", here / "scripts", Path.cwd() / "scripts"]
    for path in candidates:
        if (path / "corpus.py").is_file():
            return path
    seen = "\n".join(f"  {path}" for path in candidates)
    print("не нашёл каталог scripts — пакет его не содержит, он лежит в клоне репозитория.",
          file=sys.stderr)
    print(f"Искал:\n{seen}", file=sys.stderr)
    print("Укажите каталог явно, например:\n"
          "  FCP_SCRIPTS=$HOME/projects/fact-corpus-pipeline/scripts fcp facts", file=sys.stderr)
    raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "list"):
        print("шаги: " + ", ".join(sorted(STEPS)))
        print("пример: fcp facts --strict; fcp analyze --backend zcode --deck <колода>")
        return 0 if argv and argv[0] in ("-h", "--help", "list") else 2
    step = argv[0]
    if step not in STEPS:
        print(f"неизвестный шаг {step!r}; известны: {', '.join(sorted(STEPS))}")
        return 2
    path = scripts_dir() / STEPS[step]
    return subprocess.run([sys.executable, str(path), *argv[1:]]).returncode


if __name__ == "__main__":
    sys.exit(main())
