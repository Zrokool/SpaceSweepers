"""Run the SI Insights question set (data/insights_eval.yaml) against the real model and report how it did.

    python -m app.insights.evaluate                 # every question
    python -m app.insights.evaluate --only 3 7      # question numbers (1-based)

It needs Ollama running with the app's model. Results are printed and saved in .cache/insights-eval/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import logging
import time
from datetime import UTC, datetime

import httpx
import yaml

from app.config import get_settings
from app.insights import pipeline
from app.routes.insights import get_engine


async def ask_once(http, settings, engine, question: str) -> dict:
    library, toolbox, checker = engine
    report = None
    async for raw in pipeline.run(question=question, previous=[], http=http, settings=settings, library=library, toolbox=toolbox, checker=checker):
        event = json.loads(raw[6:])
        if event["type"] == "report":
            report = event["report"]
    return report


def judge(case: dict, report: dict) -> list[str]:
    """Problems with one answer; empty means it passed."""
    problems = []
    text = " ".join(s["text"] for s in report["answer"]).lower()
    kept = [s for s in report["answer"] if not s.get("note")]
    if case.get("expect") == "answer" and not kept:
        problems.append(f"no sentence survived the checks (mode {report['mode']})")
    for phrase in case.get("must_not", []):
        if phrase.lower() in text:
            problems.append(f"answer contains {phrase!r}")
    shown = {s["psi"] for s in report["sources"] if s.get("psi")} | {r["psi"] for r in (report.get("list") or {}).get("rows", [])}
    for psi in case.get("cites", []):
        if psi not in shown:
            problems.append(f"{psi} isn't among the sources")
    if case.get("structure") and case["structure"] not in report:
        problems.append(f"no computed {case['structure']}")
    return problems


def judge_scenario(case: dict, report: dict, seconds: float) -> list[str]:
    """A scenario answer must be the right kind, contain its expected numbers, be quick, and never present a range as a limit."""
    problems, text = [], " ".join(s["text"] for s in report["answer"])
    goal = (report.get("analysis") or {}).get("goal")
    if goal != case["goal"]:
        problems.append(f"expected a {case['goal']} answer, got {goal or report['mode']}")
    for phrase in case.get("must_include", []):
        if phrase.lower() not in text.lower() and phrase.lower() not in json.dumps(report.get("analysis") or {}).lower():
            problems.append(f"answer does not contain {phrase!r}")
    if seconds > case.get("seconds", 3):
        problems.append(f"took {seconds:.0f}s (allowed {case.get('seconds', 3)}s)")
    if case["goal"] == "threshold" and re.search(r"\d+(\.\d+)? to \d+(\.\d+)?%? (mole fraction|oxygen)", report["answer"][0]["text"]):
        problems.append("a range is presented as a limit")
    return problems


async def main(only: list[int] | None, scenarios: bool = False) -> None:
    logging.disable(logging.CRITICAL)
    settings = get_settings().model_copy(update={"run_origin": "evaluation"})      # its run logs go to nimbus-runs/evaluation/, apart from real questions
    cases = yaml.safe_load((settings.data_dir / ("scenario_eval.yaml" if scenarios else "insights_eval.yaml")).read_text(encoding="utf-8"))["questions"]
    engine = get_engine(settings.data_dir)
    rows = []
    async with httpx.AsyncClient() as http:
        installed = await __import__("app.si.ollama", fromlist=["x"]).installed_models(http, settings.ollama_url)
        if not installed or settings.si_model not in installed:
            raise SystemExit(f"The model {settings.si_model!r} isn't available in Ollama.")
        for n, case in enumerate(cases, 1):
            if only and n not in only:
                continue
            start = time.time()
            report = await ask_once(http, settings, engine, case["q"])
            problems = judge_scenario(case, report, time.time() - start) if scenarios else judge(case, report)
            rows.append({"n": n, "question": case["q"], "mode": report["mode"], "seconds": round(time.time() - start),
                         "kept": report["stats"]["kept"], "removed": report["stats"]["removed"], "evidence": report["stats"]["evidence"],
                         "answer": [s["text"] for s in report["answer"]], "removed_sentences": report["removed"], "problems": problems})
            flag = "PASS" if not problems else "FAIL"
            print(f"{n:2} {flag} {rows[-1]['seconds']:3}s kept={rows[-1]['kept']} removed={rows[-1]['removed']:<2} {case['q']}")
            for problem in problems:
                print(f"      ! {problem}")
    passed = sum(1 for r in rows if not r["problems"])
    kept = sum(r["kept"] for r in rows)
    removed = sum(r["removed"] for r in rows)
    secs = sorted(r["seconds"] for r in rows)
    print(f"\nanswer time: median {secs[len(secs) // 2]}s · slowest {secs[-1]}s · total {sum(secs)}s · "
          f"{sum(r['mode'] == 'computed' for r in rows)} answered by code without SI")
    by_rule: dict[str, int] = {}
    for r in rows:
        for x in r["removed_sentences"]:
            for rule in x.get("rules", []):
                by_rule[rule] = by_rule.get(rule, 0) + 1
    print("removed by rule:", ", ".join(f"{k} {v}" for k, v in sorted(by_rule.items(), key=lambda kv: -kv[1])) or "none")
    print(f"{passed}/{len(rows)} questions passed · sentences: {kept} verified, {removed} removed by Nimbus "
          f"({removed / max(1, kept + removed):.0%} of what the model wrote)")
    out = settings.cache_dir / "insights-eval"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps({"origin": "evaluation", "model": settings.si_model, "snapshot_fetched_at": engine[0].catalog.manifest.get("fetched_at"),
                                  "question_set": "scenario_eval.yaml" if scenarios else "insights_eval.yaml", "removed_by_rule": by_rule, "passed": passed, "total": len(rows), "rows": rows}, indent=1), encoding="utf-8")
    print(f"saved {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="*", type=int)
    parser.add_argument("--scenarios", action="store_true", help="run data/scenario_eval.yaml (questions from the target audience) instead of the general set")
    args = parser.parse_args()
    asyncio.run(main(args.only, args.scenarios))
