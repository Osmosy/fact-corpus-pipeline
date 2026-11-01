#!/usr/bin/env python3
"""Единый отчёт: все числа корпуса в одном месте, с устойчивыми ключами.

Зачем: числа в README, SKILL и кейсе переносились руками, и расхождения (43/41, 76/78)
появлялись именно так. Здесь числа считаются из артефактов, получают ключ вида
`facts.total` и пишутся в `docs/facts/REPORT.json`; `REPORT.md` — та же картина для чтения.

Источники: канон, прогоны (последний на канал), COMPARISON-*, BLIND-SPOTS-REVIEW,
SINGLE-REVIEW, STABILITY-*, INPUT-CHECK, COST, реестр требований и его гейты.

Запуск: CORPUS_ROOT=/path/to/project python3 $SKILL/report.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402

OUT = corpus.ROOT / "docs/facts/REPORT.json"
OUT_MD = corpus.ROOT / "docs/facts/REPORT.md"
GRACE = Path(__import__("os").environ.get("GRACE_REGISTRY",
                                           Path.home() / "projects/vector-grace/registry")) / "grace.py"


def decks() -> list[str]:
    if not corpus.FACTS.is_file():
        return []
    names = []
    for line in corpus.FACTS.read_text("utf-8").splitlines():
        if line.strip():
            deck = json.loads(line)["deck"]
            if deck not in names:
                names.append(deck)
    return names


def taken_by_deck() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for deck in decks():
        runs = corpus.load_runs(deck)
        chosen: set[str] = set()
        for run in runs:
            for item in run["body"]["answer"].get("selected", []):
                if isinstance(item, dict) and item.get("fact_id"):
                    chosen.add(item["fact_id"])
        out[deck] = chosen
    return out


def verdict_counts(known: set[str] | None = None) -> dict:
    """Сводка по факту, а не по модели: материал — если так сказали все, иначе расходятся."""
    path = corpus.ROOT / "docs/facts/BLIND-SPOTS-REVIEW.json"
    if not path.is_file():
        return {}
    review = json.loads(path.read_text("utf-8"))
    per_fact: dict[str, list[str]] = {}
    for body in review.values():
        for fact_id, entry in (body.get("verdicts") or {}).items():
            if known is not None and fact_id not in known:
                continue
            verdict = (entry or {}).get("verdict")
            if verdict:
                per_fact.setdefault(fact_id, []).append(verdict)
    counts = {"material": 0, "split": 0, "background": 0, "no_verdict": 0}
    for verdicts in per_fact.values():
        if len(set(verdicts)) > 1:
            counts["split"] += 1
        elif verdicts[0] == "material":
            counts["material"] += 1
        else:
            counts["background"] += 1
    return counts


def gate(name: str) -> dict:
    if not GRACE.is_file():
        return {}
    done = subprocess.run([sys.executable, str(GRACE), "--root", str(corpus.ROOT), name],
                          capture_output=True, text=True)
    text = (done.stdout or "") + (done.stderr or "")
    blocks = text.count("[BLOCK]")
    return {"exit": done.returncode, "blocking": blocks,
            "tail": text.strip().splitlines()[-1] if text.strip() else ""}


def costs() -> dict:
    path = corpus.ROOT / "docs/facts/COST.json"
    if not path.is_file():
        return {}
    body = json.loads(path.read_text("utf-8"))
    return {channel: row.get("pool_units") for channel, row in (body.get("totals") or {}).items()}


def collect() -> dict:
    facts = [json.loads(line) for line in corpus.FACTS.read_text("utf-8").splitlines()
             if line.strip()]
    taken = taken_by_deck()
    taken_all = set().union(*taken.values()) if taken else set()
    thematic = {row["fact_id"] for row in facts if row["thematic"]}
    taken_thematic = taken_all & thematic

    comparisons = {}
    per_deck: dict[str, dict] = {}
    for deck in decks():
        rows = [row for row in facts if row["deck"] == deck]
        per_deck[f"deck.{deck}.facts"] = len(rows)
        per_deck[f"deck.{deck}.thematic"] = sum(1 for row in rows if row["thematic"])
        per_deck[f"deck.{deck}.taken"] = len(taken.get(deck, set()))
    clusters_all = clusters_shared = single_total = 0
    for path in sorted(corpus.ROOT.glob("docs/facts/COMPARISON-*.json")):
        body = json.loads(path.read_text("utf-8"))
        deck = body.get("deck") or path.stem.replace("COMPARISON-", "")
        clusters = body.get("clusters") or []
        comparisons[deck] = {"runs": len(body.get("runs") or []),
                             "consensus": len(body.get("consensus") or []),
                             "single": len(body.get("single") or []),
                             "ignored": len(body.get("ignored") or []),
                             "skipped": len(body.get("runs_skipped") or [])}
        clusters_all += len(clusters)
        clusters_shared += sum(1 for cluster in clusters
                               if len({claim.get("by") for claim in cluster.get("claims") or []}) > 1)
        single_total += len(body.get("single") or [])

    blind = {row["fact_id"] for row in facts
             if row["thematic"] and row["fact_id"] not in taken_all}
    verdicts = verdict_counts(blind)

    requirements_live = proven = 0
    registry = corpus.ROOT / "docs/requirements-registry.jsonl"
    if registry.is_file():
        latest: dict[str, dict] = {}
        for line in registry.read_text("utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                latest[row["req_id"]] = row
        live = [row for row in latest.values() if row.get("status") not in ("rejected", "superseded")]
        requirements_live = len(live)
        evidence = corpus.ROOT / "docs/registry/evidence.jsonl"
        passed: set[str] = set()
        if evidence.is_file():
            for line in evidence.read_text("utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    if row.get("result") == "pass":
                        passed.add(row.get("req_id"))
        proven = len({row["req_id"] for row in live} & passed)

    single_path = corpus.ROOT / "docs/facts/SINGLE-REVIEW.json"
    single = {}
    if single_path.is_file():
        body = json.loads(single_path.read_text("utf-8"))
        single = {"total": len(body.get("ids") or {}),
                  "material": sum(1 for item in (body.get("ids") or {}).values()
                                  if item.get("verdict") == "material")}

    return {
        "facts.total": len(facts),
        "facts.thematic": len(thematic),
        "taken.total": len(taken_all),
        "taken.thematic": len(taken_thematic),
        "blind.total": len(blind),
        "blind.material": verdicts.get("material", 0),
        "blind.split": verdicts.get("split", 0),
        "blind.background": verdicts.get("background", 0),
        "blind.no_verdict": verdicts.get("no_verdict", 0),
        "comparison.clusters": clusters_all,
        "comparison.clusters_shared": clusters_shared,
        "single.total": single.get("total", single_total),
        "single.material": single.get("material", 0),
        "requirements.live": requirements_live,
        "requirements.proven": proven,
        "requirements.unproven": max(0, requirements_live - proven),
        "decks": comparisons,
        **per_deck,
        "costs.pool_units": costs(),
        "gates": {name: gate(name) for name in ("coverage", "drift", "replay")},
    }


def write_md(report: dict) -> None:
    lines = ["# Отчёт по корпусу", "",
             f"фактов {report['facts.total']}, тематических {report['facts.thematic']}, "
             f"взято {report['taken.total']} (тематических {report['taken.thematic']})", "",
             f"слепых зон {report['blind.total']}: материал {report['blind.material']}, "
             f"расходятся {report['blind.split']}, фон {report['blind.background']}", "",
             f"кластеров выводов {report['comparison.clusters']}, "
             f"сформулированы несколькими прогонами {report['comparison.clusters_shared']}", "",
             f"обязательств {report['requirements.live']}, доказано {report['requirements.proven']}, "
             f"без доказательства {report['requirements.unproven']}", ""]
    gates = report.get("gates") or {}
    for name, body in gates.items():
        if body:
            lines.append(f"гейт `{name}`: код {body['exit']}, блокирующих {body['blocking']}")
    lines.append("")
    lines.append("| ключ | значение |")
    lines.append("|---|---|")
    for key, value in report.items():
        if isinstance(value, (int, float, str)):
            lines.append(f"| `{key}` | {value} |")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    report = collect()
    corpus.write_json(OUT, report)
    write_md(report)
    print(f"фактов {report['facts.total']}, тематических {report['facts.thematic']}, "
          f"взято {report['taken.total']}, слепых {report['blind.total']}, "
          f"обязательств {report['requirements.live']} (доказано {report['requirements.proven']})")
    print(f"→ {corpus.rel(OUT)}, {corpus.rel(OUT_MD)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
