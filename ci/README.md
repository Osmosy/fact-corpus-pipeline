# CI

`selfcheck.py` — единственная проверка, которая нужна репозиторию: скрипты компилируются,
`run_all.sh` синтаксически цел, README не ссылается на несуществующие файлы, у `SKILL.md`
валидный frontmatter и канонический раздел `## Common Pitfalls`, в файлах нет секретов.

```bash
python3 ci/selfcheck.py    # код 0 — чисто, 1 — список находок
```

`github-actions.yml` — тот же прогон в GitHub Actions (матрица Python 3.11–3.13).
Файл лежит здесь, а не в `.github/workflows/`, потому что токен, которым ведётся репозиторий,
не имеет scope `workflow`. Активация — одна команда с токеном, у которого scope `workflow`
есть:

```bash
mkdir -p .github/workflows && cp ci/github-actions.yml .github/workflows/ci.yml
git add .github/workflows/ci.yml && git commit -m "ci: включить workflow" && git push
```

После первого прогона в README можно вставить бейдж:

```markdown
![selfcheck](https://github.com/Osmosy/fact-corpus-pipeline/actions/workflows/ci.yml/badge.svg)
```
