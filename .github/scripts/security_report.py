"""Normalize security-tool output into one format and render GitHub job summaries.

    # in each scan job: parse tool reports, write results/<category>.json,
    # append a per-job summary, exit 1 if the gate threshold is met
    python security_report.py collect --category sast --out results/sast.json \
        bandit=bandit.json semgrep=semgrep.json

    # in the summary job: combine every category into one overview
    python security_report.py summarize results/*.json

Secret values are never copied into results or summaries — only rule, file and line.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

SEVERITIES = ["critical", "high", "medium", "low"]
CATEGORIES = {
    "sast": ("SAST", "Static analysis of our own code"),
    "sca": ("SCA", "Known vulnerabilities in dependencies"),
    "secrets": ("Secrets", "Credentials committed to the repo or its history"),
}
TOOL_NAMES = {
    "bandit": "Bandit", "semgrep": "Semgrep", "pip-audit": "pip-audit",
    "osv": "OSV-Scanner", "gitleaks": "Gitleaks", "trufflehog": "TruffleHog",
}
ICON = {"critical": "🟥", "high": "🟧", "medium": "🟨", "low": "⬜"}
MAX_FINDINGS = 15


def finding(tool: str, severity: str, title: str, location: str = "") -> dict:
    return {"tool": tool, "severity": severity, "title": title.strip()[:200], "location": location}


def cvss_to_severity(score: str | float | None) -> str:
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "high"  # unrated advisories are treated conservatively
    return "critical" if s >= 9 else "high" if s >= 7 else "medium" if s >= 4 else "low"


# ---------- parsers: one per tool ----------

def parse_bandit(data: dict) -> list[dict]:
    return [
        finding("bandit", r["issue_severity"].lower(), f'{r["test_id"]}: {r["issue_text"]}',
                f'{r["filename"]}:{r["line_number"]}')
        for r in data.get("results", [])
    ]


def parse_semgrep(data: dict) -> list[dict]:
    sev = {"CRITICAL": "critical", "ERROR": "high", "HIGH": "high", "WARNING": "medium",
           "MEDIUM": "medium", "INFO": "low", "LOW": "low"}
    return [
        finding("semgrep", sev.get(r["extra"].get("severity", ""), "medium"),
                f'{r["check_id"].rsplit(".", 1)[-1]}: {r["extra"].get("message", "")}',
                f'{r["path"]}:{r["start"]["line"]}')
        for r in data.get("results", [])
    ]


def parse_pip_audit(data: dict) -> list[dict]:
    out = []
    for dep in data.get("dependencies", []):
        for v in dep.get("vulns", []):
            fix = ", ".join(v.get("fix_versions", [])) or "no fix yet"
            out.append(finding("pip-audit", "high", f'{v["id"]} in {dep["name"]} {dep["version"]} (fix: {fix})',
                               "requirements.txt"))
    return out


def parse_osv(data: dict) -> list[dict]:
    out = []
    for res in data.get("results", []):
        src = res.get("source", {}).get("path", "")
        for pkg in res.get("packages", []):
            p = pkg["package"]
            for group in pkg.get("groups", []):
                ids = ", ".join(group.get("aliases") or group.get("ids", []))
                out.append(finding("osv", cvss_to_severity(group.get("max_severity")),
                                   f'{ids} in {p["name"]} {p.get("version", "")}', os.path.relpath(src) if src else ""))
    return out


def parse_gitleaks(data: list) -> list[dict]:
    return [
        finding("gitleaks", "critical", f'{r["RuleID"]}: {r.get("Description", "")}',
                f'{r["File"]}:{r["StartLine"]} @ {r.get("Commit", "")[:8] or "worktree"}')
        for r in data or []
    ]


def parse_trufflehog(lines: list[dict]) -> list[dict]:
    out = []
    for r in lines:
        git = (r.get("SourceMetadata", {}).get("Data", {}) or {}).get("Git") or {}
        fs = (r.get("SourceMetadata", {}).get("Data", {}) or {}).get("Filesystem") or {}
        loc = f'{git.get("file") or fs.get("file", "?")}:{git.get("line") or fs.get("line", "?")}'
        verified = r.get("Verified", False)
        out.append(finding("trufflehog", "critical" if verified else "high",
                           f'{r.get("DetectorName", "secret")} ({"verified live" if verified else "unverified"})', loc))
    return out


def load(tool: str, path: Path):
    if not path.is_file():
        # A scanner that crashed must not look like "0 findings".
        sys.exit(f"{tool}: report {path} is missing - the scan did not complete")
    text = path.read_text()
    if tool == "trufflehog":  # JSON lines
        return [json.loads(line) for line in text.splitlines() if line.strip().startswith("{")]
    if not text.strip():
        return [] if tool == "gitleaks" else {}
    return json.loads(text)


PARSERS = {"bandit": parse_bandit, "semgrep": parse_semgrep, "pip-audit": parse_pip_audit, "osv": parse_osv,
           "gitleaks": parse_gitleaks, "trufflehog": parse_trufflehog}


def counts(findings: list[dict]) -> dict[str, int]:
    return {s: sum(f["severity"] == s for f in findings) for s in SEVERITIES}


def esc(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").replace("<", "&lt;")


def findings_table(findings: list[dict]) -> str:
    if not findings:
        return "_No findings._\n"
    ordered = sorted(findings, key=lambda f: SEVERITIES.index(f["severity"]))
    rows = ["| Severity | Tool | Finding | Location |", "|---|---|---|---|"]
    rows += [f'| {ICON[f["severity"]]} {f["severity"]} | {TOOL_NAMES[f["tool"]]} | {esc(f["title"])} | `{esc(f["location"])}` |'
             for f in ordered[:MAX_FINDINGS]]
    if len(ordered) > MAX_FINDINGS:
        rows.append(f"\n_…and {len(ordered) - MAX_FINDINGS} more — see the job log / uploaded artifacts._")
    return "\n".join(rows) + "\n"


def write_summary(markdown: str) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as f:
            f.write(markdown + "\n")
    else:
        print(markdown)


def gate_failed(c: dict[str, int], fail_on: str) -> bool:
    limit = SEVERITIES.index(fail_on)
    return any(c[s] for s in SEVERITIES[: limit + 1])


# ---------- commands ----------

def cmd_collect(args: argparse.Namespace) -> int:
    findings, tools = [], []
    for spec in args.reports:
        tool, _, path = spec.partition("=")
        if tool not in PARSERS:
            sys.exit(f"unknown tool {tool!r}")
        data = load(tool, Path(path))
        findings += PARSERS[tool](data)
        tools.append(tool)

    c = counts(findings)
    failed = gate_failed(c, args.fail_on)
    result = {"category": args.category, "tools": tools, "counts": c, "fail_on": args.fail_on,
              "passed": not failed, "findings": findings}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2))

    title, about = CATEGORIES[args.category]
    per_tool = "\n".join(
        f'| {TOOL_NAMES[t]} | ' + " | ".join(str(sum(f["severity"] == s and f["tool"] == t for f in findings))
                                             for s in SEVERITIES) + " |"
        for t in tools)
    write_summary(
        f"## {'✅' if not failed else '❌'} {title} — {about}\n\n"
        f"Gate: fail on **{args.fail_on}** or worse.\n\n"
        f"| Tool | Critical | High | Medium | Low |\n|---|---|---|---|---|\n{per_tool}\n\n"
        f"{findings_table(findings)}"
    )
    print(f"{title}: {c} -> {'FAIL' if failed else 'pass'}")
    return 1 if failed else 0


def cmd_summarize(args: argparse.Namespace) -> int:
    results = {}
    for path in args.results:
        if not Path(path).is_file():  # a job may have died before reporting
            continue
        data = json.loads(Path(path).read_text())
        results[data["category"]] = data
    job_results = json.loads(os.environ.get("NEEDS_JSON", "{}") or "{}")

    rows, all_findings, overall = [], [], True
    for key, (title, about) in CATEGORIES.items():
        r = results.get(key)
        job = job_results.get(key, {}).get("result", "unknown")
        if r is None:
            overall = False
            rows.append(f"| **{title}** | {about} | — | ⚠️ no results (job {job}) | – | – | – | – |")
            continue
        all_findings += r["findings"]
        overall &= r["passed"]
        status = "✅ Pass" if r["passed"] else "❌ Fail"
        tools = ", ".join(TOOL_NAMES[t] for t in r["tools"])
        rows.append(f"| **{title}** | {about} | {tools} | {status} | "
                    + " | ".join(str(r["counts"][s]) for s in SEVERITIES) + " |")

    total = counts(all_findings)
    run = os.environ.get("GITHUB_SERVER_URL", "") + "/" + os.environ.get("GITHUB_REPOSITORY", "") \
        + "/actions/runs/" + os.environ.get("GITHUB_RUN_ID", "")
    headline = ("✅ All security checks passed" if overall
                else f"❌ Security checks failed — {total['critical']} critical, {total['high']} high")
    write_summary(
        f"# 🛡️ SpaceSweepers security report\n\n"
        f"### {headline}\n\n"
        f"| Check | What it covers | Tools | Result | Critical | High | Medium | Low |\n"
        f"|---|---|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n\n"
        f"| | |\n|---|---|\n"
        f"| Commit | `{os.environ.get('GITHUB_SHA', 'local')[:12]}` |\n"
        f"| Ref | `{os.environ.get('GITHUB_REF_NAME', 'local')}` |\n"
        f"| Trigger | `{os.environ.get('GITHUB_EVENT_NAME', 'local')}` |\n"
        f"| Policy | SAST & SCA fail on high/critical · Secrets fail on any finding |\n"
        f"| Details | per-check sections below each job · [run]({run}) |\n\n"
        f"### Top findings\n\n{findings_table(all_findings)}"
    )
    return 0 if overall else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--category", required=True, choices=CATEGORIES)
    c.add_argument("--out", required=True)
    c.add_argument("--fail-on", default="high", choices=SEVERITIES)
    c.add_argument("reports", nargs="+", help="tool=path")
    s = sub.add_parser("summarize")
    s.add_argument("results", nargs="*")
    args = p.parse_args()
    return cmd_collect(args) if args.cmd == "collect" else cmd_summarize(args)


if __name__ == "__main__":
    sys.exit(main())
