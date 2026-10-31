# CI

`selfcheck.py` — единственная проверка, которая нужна репозиторию: скрипты компилируются,
`run_all.sh` синтаксически цел, README не ссылается на несуществующие файлы, у `SKILL.md`
валидный frontmatter и канонический раздел `## Common Pitfalls`, в файлах нет секретов.

```bash
python3 ci/selfcheck.py    # код 0 — чисто, 1 — список находок
```

## Как проверка действительно запускается

GitHub Actions в этом репозитории выключены не по желанию: токен, которым он ведётся, имеет
права только на содержимое, поэтому файл `.github/workflows/*.yml` GitHub отклоняет
(`refusing to allow a Personal Access Token to create or update workflow … without workflow
scope`). Ограничение снимается одним действием владельца — новым токеном со scope `workflow`
или кнопкой в веб-интерфейсе.

До этого проверка работает двумя путями, которые прав не требуют.

**1. Хук перед пушем — не даёт отправить сломанное состояние.**

```bash
git config core.hooksPath ci/hooks     # один раз на клон
```

Дальше каждый `git push` сначала прогоняет `ci/selfcheck.py`; при находках пуш
останавливается (`git push --no-verify` — осознанный обход).

**2. Наблюдатель — проверяет то, что уже в `origin/main`.**

```bash
ci/watch.sh          # получить origin/main, прогнать проверку, записать результат
```

Результат кладётся в `ci/last-run.json` (sha, состояние, время, первые строки вывода) и
коммитится только при смене состояния — истории не засоряет. Файл читается машиной и
человеком; в README он и есть ответ на «зелёный ли сейчас main».

**3. GitHub Actions — когда появится токен со scope `workflow`.**

```bash
mkdir -p .github/workflows && cp ci/github-actions.yml .github/workflows/ci.yml
python3 ci/selfcheck.py    # сначала убедиться, что пуш пройдёт
git add .github/workflows/ci.yml && git commit -m "ci: включить workflow" && git push
```

После первого прогона бейдж:

```markdown
![selfcheck](https://github.com/Osmosy/fact-corpus-pipeline/actions/workflows/ci.yml/badge.svg)
```
