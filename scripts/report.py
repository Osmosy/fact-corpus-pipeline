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
        shared_here = sum(1 for cluster in clusters
                          if len({claim.get("by") for claim in cluster.get("claims") or []}) > 1)
        comparisons[deck] = {"clusters": len(clusters), "shared": shared_here,
                             "runs": len(body.get("runs") or []),
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
    content_live: list[str] = []
    content_proven = legend_proven = 0
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
        legend = set((corpus.load_config(required=()) or {}).get("legend_requirements") or [])
        content_live = [row["req_id"] for row in live if row["req_id"] not in legend]
        content_proven = len([req for req in content_live if req in passed])
        legend_proven = len([req for req in legend if req in passed])

    disposition_counts: dict[str, int] = {}
    dispositions_path = corpus.ROOT / "docs/registry/dispositions.json"
    if dispositions_path.is_file():
        for entry in json.loads(dispositions_path.read_text(encoding="utf-8")).values():
            target = entry.get("target") if isinstance(entry, dict) else None
            if target:
                disposition_counts[target] = disposition_counts.get(target, 0) + 1


    # сколько «справочно» стоит на панели РБ: считаем по панели факта, а не по тексту причины
    facts_path = corpus.FACTS
    decisions_path = corpus.ROOT / "docs/facts/fact_decisions.json"
    panel_facts: dict[str, str] = {}
    if facts_path.is_file():
        for line in facts_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                panel_facts[row["fact_id"]] = row.get("panel") or ""
    fact_reqs: dict[str, list[str]] = {}
    if decisions_path.is_file():
        for fact_id, entry in json.loads(decisions_path.read_text(encoding="utf-8")).items():
            for req_id in (entry.get("req_ids") or []):
                fact_reqs.setdefault(req_id, []).append(fact_id)
    rb_info = 0
    dispositions_all = {}
    if (corpus.ROOT / "docs/registry/dispositions.json").is_file():
        dispositions_all = json.loads(
            (corpus.ROOT / "docs/registry/dispositions.json").read_text(encoding="utf-8"))
    for req_id, entry in dispositions_all.items():
        if not isinstance(entry, dict) or entry.get("target") != "info":
            continue
        if any(panel_facts.get(fact_id) == "РБ" for fact_id in fact_reqs.get(req_id, [])):
            rb_info += 1
    disposition_counts["info:РБ"] = rb_info

    # прогоны: базовые, повторы шума и отклонённые приёмкой — одно число с раскладкой
    runs_base = runs_stability = runs_rejected = 0
    if corpus.RUNS.is_dir():
        for path in sorted(corpus.RUNS.glob("*.json")):
            body = json.loads(path.read_text(encoding="utf-8"))
            if not body.get("answer") or body.get("problems"):
                runs_rejected += 1
                continue
            if corpus.run_purpose(body) == "stability":
                runs_stability += 1
            else:
                runs_base += 1

    # раскладка решений: единица — требование, категории не пересекаются
    decision_breakdown: dict[str, int] = {}
    if dispositions_all:
        facts_by_id = {row["fact_id"]: row for row in corpus.load_facts()}
        req_fact: dict[str, str] = {}
        for fact_id, entry in (json.loads(decisions_path.read_text(encoding="utf-8"))
                               if decisions_path.is_file() else {}).items():
            for req_id in (entry.get("req_ids") or []):
                req_fact[req_id] = fact_id
        counts = {"decisions.rb": 0, "decisions.profile": 0, "decisions.other": 0,
                  "decisions.exceptions": 0, "decisions.reasons_rf": 0}
        exceptions = {entry.get("req_id") for entry in
                      (corpus.load_config(required=()) or {}).get("owner_exceptions") or []
                      if isinstance(entry, dict)}
        for req_id, entry in dispositions_all.items():
            if not isinstance(entry, dict):
                continue
            if entry.get("target") == "conclusions":
                counts["decisions.exceptions" if req_id in exceptions
                       else "decisions.reasons_rf"] += 1
                continue
            if entry.get("target") != "info":
                continue
            panel = (facts_by_id.get(req_fact.get(req_id, "")) or {}).get("panel") or ""
            reason = str(entry.get("reason") or "").lower()
            if panel == "РБ":
                counts["decisions.rb"] += 1
            elif "профил" in reason or "доход" in reason:
                counts["decisions.profile"] += 1
            else:
                counts["decisions.other"] += 1
        counts["decisions.total"] = sum(1 for entry in dispositions_all.values()
                                        if isinstance(entry, dict))
        decision_breakdown = counts

    # материалы панели РБ: вердикт material у обеих моделей во втором проходе, панель из канона
    rb_material: list[str] = []
    review_path = corpus.ROOT / "docs/facts/BLIND-SPOTS-REVIEW.json"
    if review_path.is_file() and corpus.FACTS.is_file():
        review = json.loads(review_path.read_text(encoding="utf-8"))
        channels = [value for value in review.values() if isinstance(value, dict)]
        material: dict[str, int] = {}
        for channel in channels:
            for fact_id, verdict in (channel.get("verdicts") or {}).items():
                value = verdict.get("verdict") if isinstance(verdict, dict) else verdict
                if str(value) == "material":
                    material[fact_id] = material.get(fact_id, 0) + 1
        panel_of = {row["fact_id"]: row.get("panel") or ""
                    for row in corpus.load_facts()}
        rb_material = sorted(fid for fid, count in material.items()
                             if count == len(channels) and panel_of.get(fid) == "РБ")

    replay_file = corpus.ROOT / "docs/facts/REPLAY.json"
    replay_total = replay_match = 0
    if replay_file.is_file():
        body = json.loads(replay_file.read_text(encoding="utf-8"))
        replay_total = int(body.get("total") or 0)
        replay_match = int(body.get("match") or 0)

    stability: dict[str, float] = {}
    for path in sorted(corpus.ROOT.glob("docs/facts/STABILITY-*.json")):
        body = json.loads(path.read_text("utf-8"))
        if body.get("error"):
            continue
        prefix = f"stability.{body['deck']}.{body['channel'].split()[0]}"
        stability[f"{prefix}.runs"] = body.get("runs")
        stability[f"{prefix}.jaccard"] = body.get("jaccard_mean")
        stability[f"{prefix}.all"] = body.get("selected_all")
        stability[f"{prefix}.never"] = body.get("selected_none")
        stability[f"{prefix}.spearman"] = (body.get("trend") or {}).get("spearman")
        effect = body.get("position_effect") or {}
        if effect.get("runs"):
            stability[f"{prefix}.position_r"] = effect.get("combined_r")
            stability[f"{prefix}.position_p"] = effect.get("p")
            stability[f"{prefix}.mde_r"] = effect.get("mde_r")

    single_path = corpus.ROOT / "docs/facts/SINGLE-REVIEW.json"
    single: dict = {}
    if single_path.is_file():
        body = json.loads(single_path.read_text("utf-8"))
        groups = body.get("groups") or {}
        single = {"total": len(body.get("ids") or {}),
                  "material": groups.get("all_material", 0),
                  "background": groups.get("all_background", 0),
                  "split": groups.get("split", 0),
                  "unanswered": groups.get("not_all_answered", 0)}

    theme: dict = {}
    theme_path = corpus.ROOT / "docs/facts/THEME-AUDIT.json"
    if theme_path.is_file():
        body = json.loads(theme_path.read_text("utf-8"))
        theme = {"sample": body.get("sample"), "answered": body.get("answered"),
                 "mistaken": body.get("thematic"), "not_thematic": body.get("not_thematic"),
                 "share": body.get("share_mistaken")}

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
        "blind.share_thematic": round(len(blind) / len(thematic) * 100) if thematic else 0,
        "blind.share_corpus": round(len(blind) / len(facts) * 100, 1) if facts else 0.0,
        "comparison.consensus": sum(item["consensus"] for item in comparisons.values()),
        "comparison.ignored": sum(item["ignored"] for item in comparisons.values()),
        "comparison.clusters": clusters_all,
        "comparison.clusters_shared": clusters_shared,
        "single.total": single.get("total", single_total),
        "single.material": single.get("material", 0),
        "single.background": single.get("background", 0),
        "single.split": single.get("split", 0),
        "theme.sample": theme.get("sample"),
        "theme.answered": theme.get("answered"),
        "theme.mistaken": theme.get("mistaken"),
        "theme.share": theme.get("share"),
        "requirements.live": requirements_live,
        "requirements.proven": proven,
        "requirements.unproven": max(0, requirements_live - proven),
        "requirements.content_live": len(content_live),
        "requirements.content_proven": content_proven,
        "requirements.legend_proven": legend_proven,
        "requirements.info": disposition_counts.get("info", 0),
        "requirements.conclusions": disposition_counts.get("conclusions", 0),
        "requirements.rb": disposition_counts.get("info:РБ", 0),
        "owner_facts.total": len(corpus.load_owner_facts()),
        "runs.base": runs_base,
        "runs.stability": runs_stability,
        "runs.rejected": runs_rejected,
        "registry.replay_total": replay_total,
        "registry.replay_match": replay_match,
        "rb_material.total": len(rb_material),
        **decision_breakdown,
        **stability,
        "decks": comparisons,
        **{f"deck.{name}.consensus": body["consensus"] for name, body in comparisons.items()},
        **{f"deck.{name}.single": body["single"] for name, body in comparisons.items()},
        **per_deck,
        "costs.pool_units": costs(),
        "gates": {name: body for name in ("coverage", "drift", "replay")
                  for body in [gate(name)] if body and body.get("exit") in (0, 1)},
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
