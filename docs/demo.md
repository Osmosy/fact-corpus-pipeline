# Попробовать за две минуты

Демо-корпус — синтетика (см. `examples/demo-corpus/README.md`), ответы моделей уже сохранены,
сеть не нужна.

```bash
cp -r examples/demo-corpus /tmp/demo && cd /tmp/demo
export CORPUS_ROOT=$PWD
python3 <репозиторий>/scripts/validate_input.py     # входной контроль
python3 <репозиторий>/scripts/build_facts.py        # канон фактов
python3 <репозиторий>/scripts/compare_analyses.py demo-produkty-2026
python3 <репозиторий>/scripts/compare_analyses.py demo-upakovka-2026
python3 <репозиторий>/scripts/blind_spots.py
python3 <репозиторий>/scripts/cost_report.py
python3 <репозиторий>/scripts/report.py             # REPORT.json/.md
```

Или через команду: `fcp check-input`, `fcp facts`, `fcp compare --deck …`, `fcp report`.

Ожидаемые числа (сверяются в CI через `ci/demo.py` и `docs/demo-expected.report.json`):

- фактов <!-- n:facts.total -->26<!-- /n -->, тематических <!-- n:facts.thematic -->16<!-- /n -->;
- взято хотя бы одним прогоном <!-- n:taken.total -->13<!-- /n --> (все тематические);
- слепых зон <!-- n:blind.total -->3<!-- /n -->: материал <!-- n:blind.material -->0<!-- /n -->,
  расходятся <!-- n:blind.split -->2<!-- /n -->, фон <!-- n:blind.background -->1<!-- /n -->;
- кластеров выводов <!-- n:comparison.clusters -->2<!-- /n -->, оба сформулированы двумя прогонами;
- фактов «выбрал один» <!-- n:single.total -->6<!-- /n -->.

Что показывает демо: входной контроль не пропускает ошибок (0 ошибок, 24 предупреждения —
проза, повтор слайда, обрезанная ячейка), дубли панелей считаются и печатаются, сравнение
строит четыре среза, слепые зоны получают вердикты, отчёт собирает числа с ключами.
