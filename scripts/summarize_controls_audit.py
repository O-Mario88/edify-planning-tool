"""Summarize audit JUnit evidence without equating tests with UI control coverage."""

from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/audits/controls-2026-09-14"
collected = Counter()
for line in (OUT / "full-suite-collection.log").read_text().splitlines():
    if line.startswith("apps/") and "::" in line:
        collected[line.split("/")[1]] += 1
cases = defaultdict(Counter)
failures = []
root = ET.parse(OUT / "full-suite.xml").getroot()
for case in root.iter("testcase"):
    classname = case.get("classname", "")
    parts = classname.split(".")
    app = parts[1] if len(parts) > 1 and parts[0] == "apps" else "unknown"
    outcome = "passed"
    for tag in ("error", "failure", "skipped"):
        detail = case.find(tag)
        if detail is not None:
            outcome = tag
            if tag != "skipped":
                failures.append(
                    {
                        "application": app,
                        "test": classname + "." + case.get("name", ""),
                        "outcome": tag,
                        "message": detail.get("message", ""),
                        "detail": detail.text or "",
                    }
                )
            break
    cases[app][outcome] += 1
rows = [
    {
        "application": app,
        "collected_test_functions": collected[app],
        **{k: cases[app][k] for k in ("passed", "failure", "error", "skipped")},
        "count_note": "JUnit cases may include subtests; not a control coverage count",
    }
    for app in sorted(collected.keys() | cases.keys())
]
with (OUT / "application-test-results.csv").open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
(OUT / "test-failures.json").write_text(json.dumps(failures, indent=2) + "\n")
summary = {
    "junit_suites": [suite.attrib for suite in root.iter("testsuite")],
    "applications_collected": len(collected),
    "collected_tests": sum(collected.values()),
    "failed_or_errored_cases": len(failures),
    "note": "JUnit counts include subtests; use pytest console summary for test-function totals.",
}
(OUT / "execution-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))

# Preserve fresh HTML-route crawl evidence only when the corresponding test ran.
from datetime import datetime  # noqa: E402
import shutil  # noqa: E402

crawl_cases = [
    case
    for case in root.iter("testcase")
    if "test_route_crawl.RouteCrawlTest" in case.get("classname", "")
    and case.get("name") == "test_no_page_raises_for_any_role"
]
if crawl_cases:
    timestamps = [
        datetime.fromisoformat(s.get("timestamp")).timestamp()
        for s in root.iter("testsuite")
        if s.get("timestamp")
    ]
    started = min(timestamps)
    crawl_dir = ROOT / "test-results/kpi-platform-crawl"
    destination = OUT / "crawl-evidence"
    destination.mkdir(exist_ok=True)
    observations = defaultdict(list)
    role_rows = []
    for path in sorted(crawl_dir.glob("*.json")):
        if path.stat().st_mtime < started:
            continue
        data = json.loads(path.read_text())
        if not isinstance(data, list):
            continue
        shutil.copy2(path, destination / path.name)
        statuses = Counter()
        for item in data:
            statuses[str(item["status"])] += 1
            observations[item["url"]].append((path.stem, item["status"]))
        role_rows.append(
            {
                "role": path.stem,
                "html_responses": len(data),
                "status_counts": json.dumps(dict(statuses), sort_keys=True),
                "note": "HTML GET responses only, not button execution; redirects/non-HTML/exceptions/5xx omitted by crawler; consult failed tests",
            }
        )
    if role_rows:
        with (OUT / "role-route-crawl-results.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=role_rows[0].keys())
            writer.writeheader()
            writer.writerows(role_rows)
        register = OUT / "route-coverage-register.csv"
        with register.open() as f:
            rows = list(csv.DictReader(f))
        for row in rows:
            observed = observations.get(row["route"], [])
            if observed:
                statuses = Counter(status for role, status in observed)
                row["audit_execution_status"] = (
                    "Django GET HTML crawl: "
                    + str(len(observed))
                    + " role observations; statuses "
                    + json.dumps(dict(statuses), sort_keys=True)
                    + ". No individual control-click claim."
                )
        with register.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
