#!/usr/bin/env bash
# Makes the shadow comparison's copies on THIS machine (docs/migration/
# 26-shadow-writes.md). It creates and drops only databases named
# edify_shadow_*, and reads the development database once, with pg_dump.
#
#   copies.sh base   copy edify_gorn_dev into edify_shadow_base (once per data set)
#   copies.sh fresh  drop edify_shadow_a and edify_shadow_b, make both from the base
#
# EDIFY_SHADOW_BASE, EDIFY_SHADOW_A and EDIFY_SHADOW_B name other copies (so
# several people can prove saves side by side); each must still be named
# edify_shadow_*, and the defaults are the names above.
#
# The development and production databases are never written: the source is
# read by pg_dump, and every name this script creates or drops is checked.
set -euo pipefail

source_db="${EDIFY_SHADOW_SOURCE:-edify_gorn_dev}"
base="${EDIFY_SHADOW_BASE:-edify_shadow_base}"
copy_a="${EDIFY_SHADOW_A:-edify_shadow_a}"
copy_b="${EDIFY_SHADOW_B:-edify_shadow_b}"

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
    # Every name is checked before anything is dropped.
    check "$base"
    check "$copy_a"
    check "$copy_b"
    for copy in "$copy_a" "$copy_b"; do
      dropdb --if-exists "$copy"
      createdb --template="$base" "$copy"
    done
    echo "made $copy_a and $copy_b from $base"
    ;;
  *)
    echo "usage: copies.sh base | fresh" >&2
    exit 2
    ;;
esac
