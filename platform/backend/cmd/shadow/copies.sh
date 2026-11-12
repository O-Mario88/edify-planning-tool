#!/usr/bin/env bash
# Makes the shadow comparison's copies on THIS machine (docs/migration/
# 26-shadow-writes.md). It creates and drops only databases named
# edify_shadow_*, and reads the development database once, with pg_dump.
#
#   copies.sh base   copy edify_gorn_dev into edify_shadow_base (once per data set)
#   copies.sh fresh  drop edify_shadow_a and edify_shadow_b, make both from the base
#
# The development and production databases are never written: the source is
# read by pg_dump, and every name this script creates or drops is checked.
set -euo pipefail

source_db="${EDIFY_SHADOW_SOURCE:-edify_gorn_dev}"
base="edify_shadow_base"

check() {
  case "$1" in
    edify_shadow_*) ;;
    *) echo "refused: $1 is not a shadow copy" >&2; exit 2 ;;
  esac
}

case "${1:-}" in
  base)
    check "$base"
    dropdb --if-exists "$base"
    createdb "$base"
    pg_dump --no-owner --no-privileges "$source_db" | psql --quiet --set ON_ERROR_STOP=1 "$base" >/dev/null
    echo "made $base from $source_db"
    ;;
  fresh)
    for copy in edify_shadow_a edify_shadow_b; do
      check "$copy"
      dropdb --if-exists "$copy"
      createdb --template="$base" "$copy"
    done
    echo "made edify_shadow_a and edify_shadow_b from $base"
    ;;
  *)
    echo "usage: copies.sh base | fresh" >&2
    exit 2
    ;;
esac
