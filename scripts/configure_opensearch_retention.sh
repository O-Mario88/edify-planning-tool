#!/usr/bin/env bash
# Configure bounded hot-log retention for App Platform runtime streams.
#
# Credentials are resolved from DigitalOcean at runtime and never printed or
# written to disk.  Each stream writes through an alias to daily/128 MiB
# rollover indices which OpenSearch deletes after 90 days.

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <opensearch-cluster-id> [stream-alias ...]" >&2
  exit 2
fi

cluster_id=$1
shift

if [[ $# -eq 0 ]]; then
  set -- \
    edify-production-runtime \
    edify-production-scheduler \
    edify-staging-runtime \
    edify-staging-scheduler
fi

for dependency in doctl jq curl; do
  command -v "$dependency" >/dev/null || {
    echo "missing dependency: $dependency" >&2
    exit 2
  }
done

cluster_json=$(doctl databases get "$cluster_id" -o json)
status=$(jq -r '.[0].status' <<<"$cluster_json")
if [[ "$status" != "online" ]]; then
  echo "OpenSearch cluster is not online (status=$status)" >&2
  exit 1
fi

host=$(jq -r '.[0].connection.host' <<<"$cluster_json")
port=$(jq -r '.[0].connection.port' <<<"$cluster_json")
user=$(jq -r '.[0].connection.user' <<<"$cluster_json")
password=$(jq -r '.[0].connection.password' <<<"$cluster_json")
base_url="https://${host}:${port}"

os_request() {
  local method=$1
  local path=$2
  local payload=${3-}
  local curl_args=(
    --silent
    --show-error
    --fail-with-body
    --request "$method"
    --header 'Content-Type: application/json'
    --config <(printf 'user = "%s:%s"\n' "$user" "$password")
    "${base_url}${path}"
  )
  if [[ -n "$payload" ]]; then
    curl_args+=(--data-binary "$payload")
  fi
  curl "${curl_args[@]}"
}

for stream in "$@"; do
  policy_id="${stream}-90d"
  policy=$(jq -nc --arg stream "$stream" '{
    policy: {
      description: ("90-day bounded retention for " + $stream),
      default_state: "hot",
      states: [
        {
          name: "hot",
          actions: [
            {rollover: {min_index_age: "1d", min_size: "128mb"}}
          ],
          transitions: [
            {state_name: "delete", conditions: {min_index_age: "90d"}}
          ]
        },
        {
          name: "delete",
          actions: [{delete: {}}],
          transitions: []
        }
      ]
    }
  }')
  os_request PUT "/_plugins/_ism/policies/${policy_id}" "$policy" >/dev/null

  template=$(jq -nc --arg stream "$stream" --arg policy "$policy_id" '{
    index_patterns: [($stream + "-*")],
    priority: 200,
    template: {
      settings: {
        "plugins.index_state_management.policy_id": $policy,
        "plugins.index_state_management.rollover_alias": $stream,
        "number_of_shards": 1,
        "number_of_replicas": 0
      }
    }
  }')
  os_request PUT "/_index_template/${stream}-template" "$template" >/dev/null

  if ! os_request GET "/_alias/${stream}" >/dev/null 2>&1; then
    initial_index=$(jq -nc --arg stream "$stream" '{
      aliases: {($stream): {is_write_index: true}}
    }')
    os_request PUT "/${stream}-000001" "$initial_index" >/dev/null
  fi

  os_request GET "/_plugins/_ism/policies/${policy_id}" \
    | jq -e --arg policy "$policy_id" \
      '.policy.default_state == "hot" and
       (.policy.states[] | select(.name == "delete") | .actions[0].delete == {})' \
      >/dev/null
  os_request GET "/_alias/${stream}" \
    | jq -e --arg stream "$stream" \
      'to_entries | any(.value.aliases[$stream].is_write_index == true)' \
      >/dev/null
  echo "configured: ${stream} (rollover 1d/128MiB, delete 90d)"
done

