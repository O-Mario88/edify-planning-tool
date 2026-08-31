#!/usr/bin/env bash
# Reconcile the external production readiness check and its alert policies.
#
# Usage:
#   EDIFY_ALERT_EMAILS=ops@example.org scripts/configure_uptime_monitoring.sh
#
# The address must already belong to the DigitalOcean account. It is supplied
# at runtime so operational routing is not baked into source. The first account
# uptime check receives DigitalOcean's monthly free-check allowance; review the
# provider's current pricing before adding another target.

set -Eeuo pipefail

CHECK_NAME="Edify production readiness"
CHECK_TARGET="https://edifyplanning.app/api/health/ready"
CHECK_REGIONS="us_east,us_west,eu_west,se_asia"
ALERT_EMAILS="${EDIFY_ALERT_EMAILS:-}"

if [[ -z "$ALERT_EMAILS" ]]; then
  echo "REFUSING: EDIFY_ALERT_EMAILS is required." >&2
  exit 2
fi
for tool in doctl jq python3; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "REFUSING: ${tool} is required." >&2
    exit 2
  fi
done

checks_json="$(doctl monitoring uptime list -o json)"
check_count="$(jq --arg name "$CHECK_NAME" '[.[] | select(.name == $name)] | length' <<<"$checks_json")"
if [[ "$check_count" -gt 1 ]]; then
  echo "REFUSING: multiple uptime checks are named ${CHECK_NAME}." >&2
  exit 2
fi
if [[ "$check_count" -eq 0 ]]; then
  created="$(doctl monitoring uptime create "$CHECK_NAME" \
    --target "$CHECK_TARGET" --type https --regions "$CHECK_REGIONS" \
    --enabled=true -o json)"
  check_id="$(jq -r '.[0].id' <<<"$created")"
else
  check_id="$(jq -r --arg name "$CHECK_NAME" '.[] | select(.name == $name) | .id' <<<"$checks_json")"
  # doctl v1.167.0 silently sends enabled=false on `uptime update`, despite its
  # own help saying the command cannot disable a check. Use the documented API
  # and always state enabled=true. The token stays inside the child process and
  # is never printed or placed in argv.
  python3 - "$check_id" "$CHECK_NAME" "$CHECK_TARGET" "$CHECK_REGIONS" <<'PY'
import json
import subprocess
import sys
import urllib.request

check_id, name, target, regions = sys.argv[1:]
token = subprocess.check_output(["doctl", "auth", "token"], text=True).strip()
payload = json.dumps(
    {
        "enabled": True,
        "name": name,
        "regions": regions.split(","),
        "target": target,
        "type": "https",
    }
).encode()
request = urllib.request.Request(
    f"https://api.digitalocean.com/v2/uptime/checks/{check_id}",
    data=payload,
    method="PUT",
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    },
)
with urllib.request.urlopen(request, timeout=20) as response:
    result = json.load(response)
check = result.get("check", result)
if check.get("enabled") is not True:
    raise SystemExit("FAILED: provider did not leave the uptime check enabled")
PY
fi

if [[ -z "$check_id" || "$check_id" == "null" ]]; then
  echo "FAILED: the uptime check has no provider ID." >&2
  exit 1
fi
if [[ "$(doctl monitoring uptime get "$check_id" -o json | jq -r '.[0].enabled')" != "true" ]]; then
  echo "FAILED: uptime check ${check_id} is not enabled." >&2
  exit 1
fi

ensure_alert() { # name type threshold comparison period
  local name="$1" type="$2" threshold="$3" comparison="$4" period="$5"
  local alerts_json count alert_id
  alerts_json="$(doctl monitoring uptime alert list "$check_id" -o json)"
  count="$(jq --arg name "$name" '[.[] | select(.name == $name)] | length' <<<"$alerts_json")"
  if [[ "$count" -gt 1 ]]; then
    echo "REFUSING: multiple uptime alerts are named ${name}." >&2
    exit 2
  fi

  local args=(
    --name "$name"
    --type "$type"
    --threshold "$threshold"
    --comparison "$comparison"
    --period "$period"
    --emails "$ALERT_EMAILS"
  )
  if [[ "$count" -eq 0 ]]; then
    doctl monitoring uptime alert create "$check_id" "${args[@]}" >/dev/null
  else
    alert_id="$(jq -r --arg name "$name" '.[] | select(.name == $name) | .id' <<<"$alerts_json")"
    doctl monitoring uptime alert update "$check_id" "$alert_id" "${args[@]}" >/dev/null
  fi
}

ensure_alert "Edify production globally unavailable" down_global 0 greater_than 2m
ensure_alert "Edify production latency above degraded ceiling" latency 3200 greater_than 5m
ensure_alert "Edify production TLS certificate expires within 30 days" ssl_expiry 30 less_than 1h

echo "PASS: production uptime monitoring reconciled (${check_id})."
doctl monitoring uptime get "$check_id" --format ID,Name,Type,Target,Regions,Enabled
doctl monitoring uptime alert list "$check_id" \
  --format ID,Name,Type,Threshold,Comparison,Period,Emails
