"""Crawl every routed page as every role: status, exceptions, queries, time.

Runs in-process with Django's test client against the dev database, so a
500 comes back with its traceback and every request carries its query count
and wall time. Parametrised routes are filled with the first matching record
where the parameter name is recognisable; the rest are skipped and listed.
"""

import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.db import connection  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402

SCRATCH = Path(__file__).resolve().parent / "out"
ROLES = {
    "superuser": "edwin.omario@gmail.com",
    "cd": "cd@edify.org",
    "pl": "pl1@edify.org",
    "ia": "ia@edify.org",
    "accountant": "accountant@edify.org",
}
User = get_user_model()


def sample_ids():
    """First record id per recognisable parameter name."""
    from django.apps import apps

    def first(app_label, model, field="id"):
        try:
            m = apps.get_model(app_label, model)
            obj = m.objects.order_by("id").values_list(field, flat=True).first()
            return str(obj) if obj is not None else None
        except Exception:  # noqa: BLE001
            return None

    ids = {
        "activity_id": first("activities", "Activity"),
        "school_id": first("schools", "School"),
        "cluster_id": first("clusters", "Cluster"),
        "staff_id": first("accounts", "StaffProfile"),
        "user_id": str(User.objects.order_by("id").values_list("id", flat=True).first()),
        "district_id": first("geography", "District"),
        "region_id": first("geography", "Region"),
        "partner_id": first("partners", "Partner"),
        "project_id": first("projects", "SpecialProject"),
        "request_id": first("fund_requests", "AdvanceRequest"),
        "advance_id": first("fund_requests", "AdvanceRequest"),
        "budget_id": first("monthly_work_plan", "MonthlyWorkPlanBudget"),
        "debrief_id": first("debriefs", "FieldDebrief"),
        "note_id": first("monthly_work_plan", "StrategyNote"),
        "document_id": first("documents", "PolicyDocument"),
        "incident_id": first("admin_ops", "Incident"),
        "ticket_id": first("admin_ops", "SupportTicket"),
        "template_id": first("admin_ops", "MaintenanceTemplate"),
        "fy": "2026",
        "year": "2026",
        "month": "9",
        "week": "36",
        "quarter": "Q4",
        "slug": None,
        "pk": None,
        "id": None,
    }
    return {k: v for k, v in ids.items() if v}


def fill(route, ids):
    params = re.findall(r"<(?:\w+:)?(\w+)>", route)
    for p in params:
        if p not in ids:
            return None
        route = re.sub(r"<(?:\w+:)?%s>" % p, ids[p], route, count=1)
    return route


def main():
    SCRATCH.mkdir(exist_ok=True)
    inventory = json.loads(Path(__file__).resolve().parents[2] / "docs" / "platform-page-inventory.json".read_text())
    routes = sorted({p["route"] for p in inventory["pages"] if p.get("route")})
    ids = sample_ids()
    results, skipped = [], []
    wanted = sys.argv[1:] or list(ROLES)
    for role, email in ROLES.items():
        if role not in wanted:
            continue
        user = User.objects.get(email=email)
        client = Client(raise_request_exception=False)
        client.force_login(user)
        for route in routes:
            url = fill(route, ids)
            if url is None:
                if role == "superuser":
                    skipped.append(route)
                continue
            rec = {"role": role, "route": route, "url": url}
            try:
                started = time.perf_counter()
                with CaptureQueriesContext(connection) as ctx:
                    response = client.get(url, HTTP_ACCEPT="text/html")
                rec["ms"] = round((time.perf_counter() - started) * 1000)
                rec["queries"] = len(ctx.captured_queries)
                rec["status"] = response.status_code
                if response.status_code == 500:
                    body = response.content.decode(errors="replace")
                    m = re.search(r"Exception Value:</th>\s*<td><pre>(.*?)</pre>", body, re.S) or re.search(r"<title>(.*?)</title>", body, re.S)
                    rec["error"] = (m.group(1) if m else body[:200]).strip()[:300]
                elif response.status_code in (301, 302):
                    rec["location"] = response.get("Location", "")
            except Exception as exc:  # noqa: BLE001
                rec["status"] = "EXC"
                rec["error"] = "".join(traceback.format_exception_only(type(exc), exc))[:300]
                rec["trace"] = traceback.format_exc()[-1500:]
            results.append(rec)
            print(role, rec["status"], rec.get("ms"), rec.get("queries"), url, (rec.get("error") or "")[:80], flush=True)
    (SCRATCH / ("route_crawl_%s.json" % "_".join(wanted))).write_text(json.dumps({"results": results, "skipped": skipped}, indent=1))
    print("done", len(results), "requests;", len(skipped), "routes skipped for unknown parameters")


if __name__ == "__main__":
    main()
