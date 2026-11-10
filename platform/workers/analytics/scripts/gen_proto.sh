#!/usr/bin/env bash
# Generates the worker's Python protobuf and gRPC code from the shared
# contracts with the pinned grpcio-tools (requirements-dev.txt). Only the
# internal analytics contract is generated: the worker serves nothing else.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
python_bin="${PYTHON:-.venv/bin/python}"

mkdir -p gen
"$python_bin" -m grpc_tools.protoc \
  --proto_path=../../proto \
  --python_out=gen \
  --pyi_out=gen \
  --grpc_python_out=gen \
  ../../proto/edify/analytics/v1/portfolio.proto
echo "generated gen/edify/analytics/v1"
