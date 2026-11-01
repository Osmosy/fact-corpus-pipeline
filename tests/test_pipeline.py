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
import matching  # noqa: E402
import stability  # noqa: E402
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
        # стр.1: 54,8 (дважды — дубль), 10, 53,5; стр.2: 54,8; стр.3: «Одинаковая строка»
        self.assertEqual(len(facts), 5)
        self.assertEqual(len({row["fact_id"] for row in facts}), 5)
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
        self.assertEqual(len(body["ignored"]), 3)   # 10 %, повтор со стр. 2, стр. 3

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


class TestReportAndNumbers(unittest.TestCase):
    def test_report_counts_agree_with_canon(self) -> None:
        import subprocess
        tmp = Path(tempfile.mkdtemp(prefix="fcp-report-"))
        try:
            shutil.copytree(FIXTURE, tmp, dirs_exist_ok=True)
            env = {**os.environ, "CORPUS_ROOT": str(tmp)}
            for name in ("build_facts.py",):
                subprocess.run([sys.executable, str(SCRIPTS / name)], env=env,
                               capture_output=True, text=True, check=True)
            subprocess.run([sys.executable, str(SCRIPTS / "compare_analyses.py"), "mini-2026"],
                           env=env, capture_output=True, text=True, check=True)
            subprocess.run([sys.executable, str(SCRIPTS / "report.py")], env=env,
                           capture_output=True, text=True, check=True)
            report = json.loads((tmp / "docs/facts/REPORT.json").read_text("utf-8"))
            self.assertEqual(report["facts.total"], 5)
            self.assertEqual(report["facts.thematic"], 4)
            self.assertIn("blind.total", report)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_numbers_in_docs_match_snapshot(self) -> None:
        import subprocess
        done = subprocess.run([sys.executable, str(REPO / "ci/numbers.py")],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


class TestStability(CorpusCase):
    def test_identical_repeats_give_full_jaccard(self) -> None:
        self.run_script("build_facts.py")
        body = stability.stability("mini-2026", "alpha")
        self.assertEqual(body["runs"], 1)            # один принятый прогон канала
        self.assertIn("error", body)

    def test_two_repeats_are_compared(self) -> None:
        self.run_script("build_facts.py")
        runs = self.tmp / "docs/facts/runs"
        base = json.loads((runs / "mini-2026.alpha-20260101-100000.json").read_text("utf-8"))
        second = dict(base)
        second["answer"] = {"selected": base["answer"]["selected"][:1],
                            "conclusions": base["answer"]["conclusions"],
                            "not_relevant": []}
        corpus.write_json(runs / "mini-2026.alpha-20260101-110000.json", second)
        body = stability.stability("mini-2026", "alpha")
        self.assertEqual(body["runs"], 2)
        self.assertLess(body["jaccard_mean"], 1.0)
        self.assertGreater(body["selected_part"], 0)
        self.assertIn("deciles", body["position"])


class TestBackends(CorpusCase):
    """Канал описывается реестром, а не списком в коде; ключ — только из окружения."""

    def write_backends(self, body: dict) -> None:
        path = self.tmp / "docs/facts/backends.json"
        path.write_text(json.dumps({"backends": body}, ensure_ascii=False), encoding="utf-8")

    def serve(self, answer: dict) -> tuple[str, "object"]:
        """Подставной OpenAI-совместимый сервер: без сети и без токенов."""
        import http.server
        import threading

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):                                   # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(length)
                payload = {"model": "stub-1", "usage": {"prompt_tokens": 11, "completion_tokens": 7},
                           "choices": [{"message": {"content": json.dumps(answer, ensure_ascii=False)}}]}
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):                        # тишина в выводе теста
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions", server

    def test_registry_channel_is_used_and_usage_normalized(self) -> None:
        self.run_script("build_facts.py")
        facts = [json.loads(line) for line in
                 (self.tmp / "docs/facts/facts.jsonl").read_text("utf-8").splitlines()]
        answer = {"selected": [{"fact_id": facts[0]["fact_id"], "why": "важно"}],
                  "conclusions": [{"text": "вывод", "fact_ids": [facts[0]["fact_id"]]}],
                  "not_relevant": []}
        url, server = self.serve(answer)
        try:
            self.write_backends({"stub": {"kind": "openai", "url": url, "model": "stub-1"}})
            done = self.run_script("run_analysis.py", "--backend", "stub", "--deck", "mini-2026")
        finally:
            server.shutdown()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        run = json.loads(sorted((self.tmp / "docs/facts/runs").glob("mini-2026.stub-*.json"))[-1]
                         .read_text("utf-8"))
        self.assertEqual(run["usage"]["input_tokens"], 11)
        self.assertEqual(run["usage"]["output_tokens"], 7)
        self.assertIsInstance(run["seconds"], float)

    def test_unknown_channel_stops_with_list(self) -> None:
        self.run_script("build_facts.py")
        done = self.run_script("run_analysis.py", "--backend", "нет-такого", "--deck", "mini-2026")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("ollama", done.stderr + done.stdout)

    def test_builtin_channels_still_work_without_registry(self) -> None:
        spec = corpus.backend("ollama")
        self.assertEqual(spec["kind"], "openai")
        with self.assertRaises(SystemExit):
            corpus.backend("нет-такого")

    def test_cost_report_totals(self) -> None:
        runs = self.tmp / "docs/facts/runs"
        self.run_script("build_facts.py")
        corpus.write_json(runs / "mini-2026.stub-20260101-000000.json", {
            "deck": "mini-2026", "backend": "stub", "seconds": 2.0,
            "usage": {"input_tokens": 10, "output_tokens": 5, "pool_units": 15},
            "problems": [], "answer": {"selected": [], "conclusions": [], "not_relevant": []}})
        done = self.run_script("cost_report.py")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        report = json.loads((self.tmp / "docs/facts/COST.json").read_text("utf-8"))
        self.assertEqual(report["totals"]["stub"]["pool_units"], 15)
        self.assertEqual(report["totals"]["stub"]["runs"], 1)


class TestMatching(unittest.TestCase):
    """Пересказ не должен давать ложный провал, а «похоже по словам» — давать ложный pass."""

    LABEL = "Высокое содержание мяса"
    VALUE = "39 %"

    def test_paraphrase_with_same_number_matches(self) -> None:
        result = matching.match(self.LABEL, self.VALUE,
                                "Потребители выбирают продукты с высоким содержанием мяса — 39 %.")
        self.assertTrue(result["matched"], result)
        self.assertIn("мяс", result["found"])

    def test_stems_without_number_do_not_match(self) -> None:
        result = matching.match(self.LABEL, self.VALUE,
                                "Продукты с высоким содержанием мяса покупают чаще.")
        self.assertFalse(result["matched"], result)
        self.assertFalse(result["number_found"])

    def test_number_without_stems_does_not_match(self) -> None:
        result = matching.match(self.LABEL, self.VALUE,
                                "Доля рынка выросла до 39 % за год.")
        self.assertFalse(result["matched"], result)
        self.assertLess(result["share"], 0.6)

    def test_explanation_lists_found_and_missing(self) -> None:
        result = matching.match("Простой состав продукта", "40 %",
                                "Простой состав — 40 % покупателей.")
        self.assertTrue(result["found"])
        self.assertTrue(result["missing"])                       # «продукт» в предложении нет
        self.assertFalse(set(result["found"]) & set(result["missing"]))
        self.assertIn(matching.stems("состав")[0], result["found"])


class InputCheckCase(unittest.TestCase):
    """Входной контроль — на колоде с дефектами: у каждого кода своя находка."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="fcp-input-"))
        shutil.copytree(REPO / "tests/fixtures/input-check", self.tmp, dirs_exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_script(self, name: str, *args: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "CORPUS_ROOT": str(self.tmp)}
        return subprocess.run([sys.executable, str(SCRIPTS / name), *args],
                              capture_output=True, text=True, env=env, timeout=120)

    def report(self) -> dict:
        return json.loads((self.tmp / "docs/facts/INPUT-CHECK.json").read_text("utf-8"))


class TestValidateInput(InputCheckCase):
    def test_every_code_has_its_finding(self) -> None:
        done = self.run_script("validate_input.py")
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        codes = {item["code"] for item in self.report()["decks"]["broken-2026"]["findings"]}
        self.assertEqual(codes, {"page_without_anchor", "ragged_table", "duplicate_page",
                                 "repeated_slide", "truncated_cell", "panel_ambiguous",
                                 "value_not_on_page", "label_not_substring", "page_missing",
                                 "value_in_prose"})

    def test_errors_and_warnings_are_separated(self) -> None:
        self.run_script("validate_input.py")
        totals = self.report()["totals"]
        self.assertEqual(totals["errors"], 3)       # два провала подписи/значения и страница-призрак
        self.assertEqual(totals["warnings"], 7)

    def test_value_in_prose_is_warning_not_error(self) -> None:
        self.run_script("validate_input.py")
        findings = self.report()["decks"]["broken-2026"]["findings"]
        prose = [item for item in findings if item["code"] == "value_in_prose"]
        self.assertEqual(len(prose), 1, findings)
        self.assertEqual(prose[0]["level"], "warn")
        self.assertEqual(prose[0]["page"], 7)

    def test_clean_deck_returns_zero(self) -> None:
        deck = self.tmp / "decks/clean-2026/clean-2026.md"
        deck.parent.mkdir(parents=True)
        deck.write_text("## Слайд 1 — Чисто\n\n| Показатель | Доля |\n|---|---|\n"
                        "| Нравится вкус | 54,8 % |\n", encoding="utf-8")
        facts = self.tmp / "docs/registry/page_facts.json"
        data = json.loads(facts.read_text("utf-8"))
        data["decks"] = {"clean-2026": {"deck_sha256": "clean", "pages": {"1": {"facts": [
            {"label": "Нравится вкус", "value": "54,8 %", "verified": True}]}}}}
        facts.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        done = self.run_script("validate_input.py")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.report()["totals"]["warnings"], 0)

    def test_strict_drops_facts_with_input_errors(self) -> None:
        self.run_script("validate_input.py")
        done = self.run_script("build_facts.py", "--strict")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        rejected = [json.loads(line) for line in
                    (self.tmp / "docs/facts/facts-rejected.jsonl").read_text("utf-8").splitlines()]
        reasons = {row["reason"] for row in rejected}
        self.assertTrue(any("value_not_on_page" in reason for reason in reasons), reasons)
        self.assertTrue(any("label_not_substring" in reason for reason in reasons), reasons)
        facts = [json.loads(line) for line in
                 (self.tmp / "docs/facts/facts.jsonl").read_text("utf-8").splitlines()]
        self.assertNotIn("Простой состав", {row["label"] for row in facts})


class TestBlindSnapshot(CorpusCase):
    def setUp(self) -> None:
        super().setUp()
        self.run_script("build_facts.py")

    def test_snapshot_lists_ids(self) -> None:
        done = self.run_script("blind_spots.py")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        snapshot = json.loads((self.tmp / "docs/facts/BLIND-SPOTS-IDS.json").read_text("utf-8"))
        self.assertEqual(snapshot["count"], len(snapshot["ids"]))
        self.assertTrue(snapshot["ids"])

    def test_diff_reports_what_left_the_theme(self) -> None:
        self.run_script("blind_spots.py")
        config = self.tmp / "docs/facts/config.json"
        data = json.loads(config.read_text("utf-8"))
        data["theme_stems"] = ["нетакойосновы"]        # тема пустеет: всё уходит из слепых зон
        config.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.run_script("build_facts.py")
        done = self.run_script("blind_spots.py", "--diff")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("пришли 0", done.stdout.replace(",", ""))
        self.assertIn("ушёл", done.stdout)


class TestSkippedRun(CorpusCase):
    def setUp(self) -> None:
        super().setUp()
        self.run_script("build_facts.py")

    def test_rejected_latest_run_is_reported(self) -> None:
        done = self.run_script("compare_analyses.py", "mini-2026")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("последний прогон отклонён", done.stdout)
        self.assertIn("mini-2026.alpha-20260102-100000", done.stdout)
        body = json.loads((self.tmp / "docs/facts/COMPARISON-mini-2026.json").read_text("utf-8"))
        self.assertEqual([note["backend"] for note in body["runs_skipped"]], ["alpha"])
        self.assertIn("mini-2026.alpha-20260102-100000", body["runs_skipped"][0]["skipped"])

    def test_skipped_runs_reach_the_markdown(self) -> None:
        self.run_script("compare_analyses.py", "mini-2026")
        text = (self.tmp / "docs/facts/COMPARISON-mini-2026.md").read_text("utf-8")
        self.assertIn("последний прогон канала отклонён", text)


class TestAmbiguity(CorpusCase):
    def setUp(self) -> None:
        super().setUp()
        self.run_script("build_facts.py")

    def test_same_label_and_value_in_two_panels_is_not_linked(self) -> None:
        row, reason = corpus.resolve_row("mini-2026", 3, "Одинаковая строка", "42 %")
        self.assertIsNone(row)
        self.assertIn("неоднозначно", reason)
        self.assertIn("РФ", reason)
        self.assertIn("РБ", reason)

    def test_apply_decisions_lists_ambiguous_fact_for_human(self) -> None:
        done = self.run_script("apply_fact_decisions.py")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("нужно решение человека", done.stdout)
        decisions = json.loads((self.tmp / "docs/facts/fact_decisions.json").read_text("utf-8"))
        ambiguous = [entry for entry in decisions.values()
                     if entry["label"] == "Одинаковая строка"]
        self.assertEqual(len(ambiguous), 1)
        self.assertEqual(ambiguous[0]["req_ids"], [])


class TestRbToInfo(CorpusCase):
    def setUp(self) -> None:
        super().setUp()
        self.run_script("build_facts.py")

    def test_dry_run_finds_requirement_and_writes_nothing(self) -> None:
        done = self.run_script("rb_to_info.py", "--panel", "РБ")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("REQ-0001", done.stdout)
        self.assertFalse((self.tmp / "docs/facts/fact_decisions.json").exists())
        self.assertIn("пробный прогон", done.stdout)

    def test_apply_writes_page_and_req_ids(self) -> None:
        done = self.run_script("rb_to_info.py", "--panel", "РБ", "--apply")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        decisions = json.loads((self.tmp / "docs/facts/fact_decisions.json").read_text("utf-8"))
        linked = [entry for entry in decisions.values() if "REQ-0001" in entry.get("req_ids", [])]
        self.assertEqual(len(linked), 1, decisions)
        self.assertEqual(linked[0]["page"], 1)
        self.assertEqual(linked[0]["target"], "info")
        # требование без факта не создаёт ключ в решениях
        self.assertNotIn("REQ-0002", [rid for entry in decisions.values()
                                      for rid in entry.get("req_ids", [])])


class TestConfigRequiresPerStep(CorpusCase):
    def test_build_facts_without_decided_by(self) -> None:
        config = self.tmp / "docs/facts/config.json"
        data = json.loads(config.read_text("utf-8"))
        data.pop("decided_by")
        config.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        done = self.run_script("build_facts.py")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        failed = self.run_script("apply_fact_decisions.py")
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("decided_by", failed.stderr + failed.stdout)
        self.assertNotIn("question", failed.stderr + failed.stdout)


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
        self.assertEqual(len(decisions), 3)
        for fact_id, decision in decisions.items():
            self.assertEqual(decision["page"] in (1, 2, 3), True, decision)
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
