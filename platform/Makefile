# Edify platform (Go gateway, contracts, Python worker, React Native app,
# Next.js web app).
# Nothing here touches the existing Django application or any database that
# is not a local development or test database.

# Relative on purpose: the checkout path may contain spaces.
BIN := .bin

.PHONY: tools proto proto-lint proto-breaking proto-check backend-vet backend-test worker-test mobile-test web-test test

# Build the pinned generators (versions come from tools/go.mod).
tools:
	@mkdir -p $(BIN)
	cd tools && GOBIN="$$(cd ../$(BIN) && pwd)" go install tool

proto-lint: tools
	cd proto && ../$(BIN)/buf lint
	cd proto && ../$(BIN)/buf format --diff --exit-code

# Compare the contracts with the migration branch's last pushed state. In a
# git worktree, point BREAKING_AGAINST at the main checkout's .git directory.
BREAKING_AGAINST ?= ../../.git\#branch=origin/feature/edify-go-rn-migration,subdir=platform/proto
proto-breaking: tools
	cd proto && ../$(BIN)/buf breaking --against "$(BREAKING_AGAINST)"

proto: tools
	cd proto && ../$(BIN)/buf generate
	cd proto && ../$(BIN)/buf generate --template buf.gen.web.yaml
	cd workers/analytics && ./scripts/gen_proto.sh

# Generated code must match the contracts that are committed.
proto-check: proto
	git diff --exit-code -- backend/gen mobile/src/gen web/src/gen workers/analytics/gen

backend-vet:
	cd backend && go vet ./...

backend-test:
	cd backend && go test ./...

worker-test:
	cd workers/analytics && .venv/bin/python -m pytest -q

mobile-test:
	cd mobile && npm run typecheck && npm test

web-test:
	cd web && npm run typecheck && npm run lint && npm test

test: backend-vet backend-test worker-test mobile-test web-test
