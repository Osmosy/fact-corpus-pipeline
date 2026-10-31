"""Тесты конвейера на синтетическом корпусе — без сети и без данных закрытых колод.

Корпус-фикстура: одна колода, два слайда, панели РФ и РБ с одинаковой подписью, повтор
слайда, один факт без `verified`, один без значения, три прогона (два принятых от разных
каналов и один отклонённый с выдуманным id).

Проверяется то, на чём конвейер уже ошибался: приёмка всех трёх списков ответа, отсев
отклонённых прогонов, «последний прогон на канал», тематичность по началу слова,
стабильность fact_id, привязка факта к строке с учётом панели, поведение приложения.

Запуск: python3 -m unittest discover -s tests -t .    (или pytest -q)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
FIXTURE = REPO / "tests/fixtures/mini-corpus"

sys.path.insert(0, str(SCRIPTS))
import corpus  # noqa: E402
import run_analysis  # noqa: E402


class CorpusCase(unittest.TestCase):
    """Каждый тест — на свежей копии фикстуры: скрипты пишут в корпус."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="fcp-test-"))
        shutil.copytree(FIXTURE, self.tmp, dirs_exist_ok=True)
        # модуль corpus читает пути при импорте — для прямых вызовов переносим их на копию
        corpus.ROOT = self.tmp
        for name, rel in (("FACTS", "docs/facts/facts.jsonl"),
                          ("CONFIG", "docs/facts/config.json"),
                          ("PLAN", "docs/facts/plan.json"),
                          ("DECISIONS", "docs/facts/fact_decisions.json"),
                          ("DISPOSITIONS", "docs/registry/dispositions.json"),
                          ("PAGE_FACTS", "docs/registry/page_facts.json"),
                          ("REQUIREMENTS", "docs/requirements-registry.jsonl"),
                          ("RUNS", "docs/facts/runs"),
                          ("REJECTED_FACTS", "docs/facts/facts-rejected.jsonl")):
            setattr(corpus, name, self.tmp / rel)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_script(self, name: str, *args: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "CORPUS_ROOT": str(self.tmp)}
        env.pop("APPENDIX_INFO", None)
        return subprocess.run([sys.executable, str(SCRIPTS / name), *args],
                              capture_output=True, text=True, env=env, timeout=120)

    def facts(self) -> list[dict]:
        path = self.tmp / "docs/facts/facts.jsonl"
        return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


class TestBuildFacts(CorpusCase):
    def test_verified_rejected_and_duplicates(self) -> None:
        done = self.run_script("build_facts.py")
        self.assertEqual(done.returncode, 0, done.stderr)
        facts = self.facts()
        # стр.1: 54,8 (дважды — дубль), 10, 53,5; стр.2: 54,8 (другая страница — не дубль)
        self.assertEqual(len(facts), 4)
        self.assertEqual(len({row["fact_id"] for row in facts}), 4)
        self.assertIn("дублей: 1", done.stdout)

        rejected = (self.tmp / "docs/facts/facts-rejected.jsonl").read_text("utf-8").splitlines()
        reasons = " ".join(rejected)
        self.assertIn("verified", reasons)
        self.assertIn("пустая подпись", reasons)

    def test_thematic_by_word_start(self) -> None:
        self.run_script("build_facts.py")
        labels = {row["label"]: row["thematic"] for row in self.facts()}
        self.assertTrue(labels["Нравится вкус продукта"])
        # «оценка» не должна считаться тематической по основе «цен»
        self.assertFalse(corpus.is_thematic("Оценка без числа", ["цен"]))
        self.assertTrue(corpus.is_thematic("Ценность продукта", ["цен"]))
        self.assertFalse(corpus.is_thematic("Процент выбора", ["цен"]))

    def test_fact_id_is_stable_between_runs(self) -> None:
        self.run_script("build_facts.py")
        first = (self.tmp / "docs/facts/facts.jsonl").read_text("utf-8")
        self.run_script("build_facts.py")
        second = (self.tmp / "docs/facts/facts.jsonl").read_text("utf-8")
        self.assertEqual(first, second)

    def test_without_config_stops_with_hint(self) -> None:
        (self.tmp / "docs/facts/config.json").unlink()
        done = self.run_script("build_facts.py")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("config.json", done.stderr + done.stdout)


class TestCompare(CorpusCase):
    def setUp(self) -> None:
        super().setUp()
        self.run_script("build_facts.py")

    def test_rejected_run_is_not_counted(self) -> None:
        done = self.run_script("compare_analyses.py", "mini-2026")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        body = json.loads((self.tmp / "docs/facts/COMPARISON-mini-2026.json").read_text("utf-8"))
        self.assertEqual(len(body["runs"]), 2, body["runs"])          # alpha и beta, без отклонённого
        self.assertEqual(len(body["consensus"]), 1)
        self.assertEqual(len(body["single"]), 1)
        self.assertEqual(len(body["ignored"]), 2)   # 10 % и повтор со стр. 2

    def test_include_rejected_flag(self) -> None:
        done = self.run_script("compare_analyses.py", "mini-2026", "--include-rejected",
                               "--all-runs")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        body = json.loads((self.tmp / "docs/facts/COMPARISON-mini-2026.json").read_text("utf-8"))
        self.assertIn("alpha (mini-2026.alpha-20260102-100000)", body["runs"])

    def test_conclusions_cluster_by_overlap(self) -> None:
        self.run_script("compare_analyses.py", "mini-2026")
        body = json.loads((self.tmp / "docs/facts/COMPARISON-mini-2026.json").read_text("utf-8"))
        agreed = [cluster for cluster in body["clusters"]
                  if len({claim["by"] for claim in cluster["claims"]}) == 2]
        self.assertEqual(len(agreed), 1, body["clusters"])


class TestValidate(unittest.TestCase):
    def facts(self) -> list[dict]:
        return [{"fact_id": "F-1"}, {"fact_id": "F-2"}]

    def test_unknown_id_in_conclusions_is_problem(self) -> None:
        answer = json.dumps({
            "selected": [{"fact_id": "F-1", "why": "ок"}],
            "conclusions": [{"text": "вывод", "fact_ids": ["F-000000000000"]}],
            "not_relevant": [],
        })
        _, problems = run_analysis.validate(answer, self.facts())
        self.assertTrue(any("conclusions" in problem for problem in problems), problems)

    def test_unknown_id_in_not_relevant_is_problem(self) -> None:
        answer = json.dumps({
            "selected": [{"fact_id": "F-1", "why": "ок"}],
            "conclusions": [{"text": "вывод", "fact_ids": ["F-1"]}],
            "not_relevant": [{"fact_id": "F-999", "why": "мимо"}],
        })
        _, problems = run_analysis.validate(answer, self.facts())
        self.assertTrue(any("not_relevant" in problem for problem in problems), problems)

    def test_garbage_answer_is_problem_not_exception(self) -> None:
        for answer in ("", "не json", json.dumps([1, 2, 3]), json.dumps({"selected": "нет"})):
            data, problems = run_analysis.validate(answer, self.facts())
            self.assertTrue(problems, answer)

    def test_clean_answer_has_no_problems(self) -> None:
        answer = json.dumps({
            "selected": [{"fact_id": "F-1", "why": "ок"}],
            "conclusions": [{"text": "вывод", "fact_ids": ["F-1"]}],
            "not_relevant": [{"fact_id": "F-2", "why": "фон"}],
        })
        data, problems = run_analysis.validate(answer, self.facts())
        self.assertEqual(problems, [])
        self.assertIsNotNone(data)


class TestExtractObject(unittest.TestCase):
    def test_braces_inside_string_do_not_break_parsing(self) -> None:
        text = 'прелюдия {"selected": [], "why": "условие {a: b} внутри строки", "conclusions": []} хвост'
        found = corpus.extract_object(text, ("selected",))
        self.assertEqual(found["why"], "условие {a: b} внутри строки")

    def test_trailing_comma_is_tolerated(self) -> None:
        text = '{"verdicts": [{"fact_id": "F-1", "verdict": "material"},]}'
        found = corpus.extract_object(text, ("verdicts",))
        self.assertEqual(found["verdicts"][0]["verdict"], "material")

    def test_comma_inside_string_is_kept(self) -> None:
        text = '{"selected": [{"fact_id": "F-1", "why": "вкус, аромат,"}]}'
        found = corpus.extract_object(text, ("selected",))
        self.assertEqual(found["selected"][0]["why"], "вкус, аромат,")

    def test_envelope_response(self) -> None:
        text = '{"sessionId": "s1", "response": "{\\"selected\\": [{\\"fact_id\\": \\"F-1\\"}]}"}'
        envelope = corpus.extract_object(text, ("sessionId",))
        inner = corpus.extract_object(envelope["response"], ("selected",))
        self.assertEqual(inner["selected"][0]["fact_id"], "F-1")


class TestRows(CorpusCase):
    def test_panel_rows_are_distinguished_by_page(self) -> None:
        rows = corpus.rows("mini-2026")
        same_label = [row for row in rows if row["cells"][0] == "Нравится вкус продукта"]
        self.assertEqual(len(same_label), 3)
        self.assertEqual({row["panel"] for row in same_label}, {"РФ", "РБ", ""})
        russian = corpus.row_for_fact("mini-2026", 1, "Нравится вкус продукта", "54,8 %")
        self.assertEqual(russian["panel"], "РФ")
        belarus = corpus.row_for_fact("mini-2026", 1, "Нравится вкус продукта", "53,5 %")
        self.assertEqual(belarus["panel"], "РБ")

    def test_value_is_compared_as_whole_cell(self) -> None:
        # «5 %» не должно находиться внутри «54,8 %»
        self.assertIsNone(corpus.row_for_fact("mini-2026", 1, "Нравится вкус продукта", "5 %"))


class TestDecisions(CorpusCase):
    def setUp(self) -> None:
        super().setUp()
        self.run_script("build_facts.py")

    def test_decisions_link_requirements_and_keep_page(self) -> None:
        done = self.run_script("apply_fact_decisions.py")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        decisions = json.loads((self.tmp / "docs/facts/fact_decisions.json").read_text("utf-8"))
        self.assertEqual(len(decisions), 2)
        for fact_id, decision in decisions.items():
            self.assertEqual(decision["page"] in (1, 2), True, decision)
            self.assertIn("req_ids", decision)
        self.assertEqual({d["target"] for d in decisions.values()}, {"conclusions", "info"})

    def test_invalid_target_stops(self) -> None:
        plan = self.tmp / "docs/facts/plan.json"
        plan.write_text(json.dumps({"F-344ccae9ed26": ["в_выводы", "опечатка"]}), encoding="utf-8")
        done = self.run_script("apply_fact_decisions.py")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("вне", done.stderr + done.stdout)

    def test_appendix_single_generator(self) -> None:
        self.run_script("apply_fact_decisions.py")
        reviews = self.tmp / "reviews/2026-01-01-mini"
        reviews.mkdir(parents=True)
        (reviews / "APPENDIX-INFO.md").write_text("старое приложение\n", encoding="utf-8")
        done = self.run_script("build_appendix.py")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        text = (reviews / "APPENDIX-INFO.md").read_text("utf-8")
        self.assertIn("Справочно", text)
        self.assertIn("вторая панель", text)

    def test_two_appendices_stop_with_hint(self) -> None:
        self.run_script("apply_fact_decisions.py")
        for name in ("2026-01-01-a", "2026-01-02-b"):
            folder = self.tmp / "reviews" / name
            folder.mkdir(parents=True)
            (folder / "APPENDIX-INFO.md").write_text("—\n", encoding="utf-8")
        done = self.run_script("build_appendix.py")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("APPENDIX_INFO", done.stderr + done.stdout)


if __name__ == "__main__":
    unittest.main()
