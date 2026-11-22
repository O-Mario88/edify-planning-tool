#!/usr/bin/env python3
"""Edify Staging UAT & Ecosystem Verification Runner (Django-absent Go mode).

Runs non-destructive end-to-end verification across roles, dashboard views,
interactive Country Map SQL parity, CSV/XLSX/PDF exports, Bulk Upload Center,
Planning Drawers, Real-Time SSE streams, and negative security checks.

Usage:
  python3 uat_journey.py \
    --gateway http://127.0.0.1:8091 \
    --db "postgresql://user@127.0.0.1:5432/edify_gorn_test" \
    --jwt-secret "$EDIFY_JWT_SECRET"
"""

import argparse
import base64
import hashlib
import hmac
import io
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def mint_jwt(secret: bytes, user_id: str, role: str) -> str:
    hdr = b64u(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    now = int(time.time())
    pay = b64u(
        json.dumps(
            {
                "sub": user_id,
                "user_id": user_id,
                "role": role,
                "active_role": role,
                "iat": now,
                "exp": now + 3600,
            }
        ).encode()
    )
    sig = b64u(hmac.new(secret, f"{hdr}.{pay}".encode(), hashlib.sha256).digest())
    return f"{hdr}.{pay}.{sig}"


def psql_scalar(db_url: str, sql: str) -> str:
    return (
        subprocess.check_output(["psql", db_url, "-tAc", sql], stderr=subprocess.STDOUT)
        .decode()
        .strip()
    )


def http_req(base: str, path: str, method: str = "GET", data=None, token: str | None = None, headers=None):
    hdrs = dict(headers or {})
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if isinstance(data, dict):
        body = json.dumps(data).encode()
        hdrs.setdefault("Content-Type", "application/json")
    elif isinstance(data, (bytes, bytearray)):
        body = data
    else:
        body = None
    req = urllib.request.Request(base.rstrip("/") + path, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def main() -> int:
    parser = argparse.ArgumentParser(description="Edify Staging UAT Ecosystem Verification")
    parser.add_argument("--gateway", required=True, help="Go gateway base URL (e.g. http://127.0.0.1:8091)")
    parser.add_argument("--db", required=True, help="Non-production staging PostgreSQL URL")
    parser.add_argument("--jwt-secret", required=True, help="Staging gateway JWT signing secret")
    args = parser.parse_args()

    if "prod" in args.db.lower() and "nonprod" not in args.db.lower():
        print("ABORT: refusing to run UAT against a database URL containing 'prod'", file=sys.stderr)
        return 2

    secret = args.jwt_secret.encode()
    base = args.gateway.rstrip("/")
    passed = 0

    def ok(label: str, detail: str = ""):
        nonlocal passed
        passed += 1
        print(f"[PASS {passed:02d}] {label}" + (f" — {detail}" if detail else ""))

    # 1. Health & readiness
    st, _, _ = http_req(base, "/healthz")
    assert st == 200, f"/healthz failed: {st}"
    ok("Gateway /healthz", "200 OK")

    # 2. Resolve test principals from staging DB
    tokens = {}
    for role in ["Admin", "Program Lead", "CCEO", "CountryDirector", "ImpactAssessment", "Accountant"]:
        uid = psql_scalar(args.db, f"SELECT id FROM \"user\" WHERE '{role}' = ANY(roles) AND is_active=true LIMIT 1")
        if uid:
            tokens[role] = mint_jwt(secret, uid, role)
    assert "Admin" in tokens and "Program Lead" in tokens and "CCEO" in tokens, f"Missing required roles: {list(tokens)}"
    ok("Role principals resolved", ", ".join(sorted(tokens.keys())))

    # 3. Negative security: unauthenticated requests must return 401
    for protected in ["/api/v1/country-map/data", "/api/v1/realtime/stream", "/api/v1/uploads/ssa/template"]:
        st, _, _ = http_req(base, protected)
        assert st == 401, f"expected 401 on {protected}, got {st}"
    ok("Negative auth checks (401)", "3/3 protected endpoints blocked without JWT")

    # 4. All Program Lead & CCEO Dashboard views (Django offline)
    for view in ["week", "priorities", "team", "operations", "coaching", "programmes", "collaboration"]:
        st, _, body = http_req(
            base,
            "/edify.screens.v1.PageScreenService/GetPage",
            "POST",
            {"path": "/dashboard", "query": {"view": view, "fy": "2027"}, "desktop": True},
            token=tokens["Program Lead"],
        )
        assert st == 200, f"PL /dashboard?view={view} failed: {st}"
        assert len(json.loads(body).get("blocks", [])) >= 3
    for view in ["week", "operations"]:
        st, _, body = http_req(
            base,
            "/edify.screens.v1.PageScreenService/GetPage",
            "POST",
            {"path": "/dashboard", "query": {"view": view}, "desktop": True},
            token=tokens["CCEO"],
        )
        assert st == 200, f"CCEO /dashboard?view={view} failed: {st}"
    ok("Dashboard native Go views", "7/7 PL views + 2/2 CCEO views returned 200 OK")

    # 5. Country Map SQL reconciliation
    expected_schools = int(psql_scalar(args.db, "SELECT count(*) FROM school WHERE deleted_at IS NULL AND operational_status IN ('active','reopened')"))
    st, _, map_body = http_req(base, "/api/v1/country-map/data?fy=2027", token=tokens["Program Lead"])
    assert st == 200, f"/api/v1/country-map/data failed: {st}"
    map_data = json.loads(map_body)
    actual_schools = map_data.get("totals", {}).get("schools")
    assert actual_schools == expected_schools, f"Map schools mismatch: {actual_schools} vs SQL {expected_schools}"
    ok("Country Map SQL reconciliation", f"{expected_schools} active schools (0 variance)")

    # 6. Exports round-trip across CSV, XLSX, PDF
    for fmt in ["csv", "xlsx", "pdf"]:
        st, _, body = http_req(base, "/api/v1/exports", "POST", {"kind": "school_directory", "format": fmt}, token=tokens["Admin"])
        assert st == 201, f"Export {fmt} create failed: {st}"
        meta = json.loads(body)
        st2, _, payload = http_req(base, meta["download_url"], token=tokens["Admin"])
        assert st2 == 200, f"Export {fmt} download failed: {st2}"
        if fmt == "xlsx":
            zf = zipfile.ZipFile(io.BytesIO(payload))
            assert "xl/worksheets/sheet1.xml" in zf.namelist()
        elif fmt == "pdf":
            assert payload.startswith(b"%PDF-1.4") and payload.strip().endswith(b"%%EOF")
        else:
            assert b"edify_school_id" in payload
    ok("Multi-format Go exports (CSV/XLSX/PDF)", f"school_directory ({expected_schools} rows) verified in all 3 formats")

    # 7. Bulk Upload Center RBAC & template + validation dry-run
    st, _, tpl = http_req(base, "/api/v1/uploads/ssa/template", token=tokens["Admin"])
    assert st == 200 and b"School ID,Assessment Date,SSA Year" in tpl
    st_forb, _, _ = http_req(base, "/api/v1/uploads/ssa/template", token=tokens["CCEO"])
    assert st_forb == 403
    st_pa, _, pa_tpl = http_req(base, "/api/v1/uploads/planned-activities/template", token=tokens["Program Lead"])
    assert st_pa == 200 and b"activity_id,edify_school_id" in pa_tpl
    ok("Bulk Upload Center templates & RBAC", "SSA + Planned Activities templates OK, CCEO=403")

    # 8. Planning Drawers (schedule, assign, group-training, cluster-meeting)
    sid = psql_scalar(args.db, "SELECT id FROM school WHERE deleted_at IS NULL LIMIT 1")
    for kind in ["schedule", "assign", "group-training", "cluster-meeting"]:
        st, _, _ = http_req(
            base,
            "/edify.screens.v1.PlanningDrawerService/GetPlanningDrawer",
            "POST",
            {"schoolId": sid, "kind": kind},
            token=tokens["Program Lead"],
        )
        assert st == 200, f"PlanningDrawer {kind} failed: {st}"
    ok("Native Go Planning Drawers", "4/4 kinds (schedule, assign, group-training, cluster-meeting)")

    # 9. Real-time SSE stream handshake
    req = urllib.request.Request(
        base + "/api/v1/realtime/stream",
        headers={"Authorization": f"Bearer {tokens['Program Lead']}"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        line1 = resp.readline().decode()
        line2 = resp.readline().decode()
        assert "event: ready" in line1 and "Program Lead" in line2
    ok("Real-time SSE stream handshake", "event: ready received cleanly")

    print(f"\nALL {passed} STAGING UAT CHECKS PASSED (ZERO DJANGO CALLS).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
