# Edify gateway image. Build context is platform/:
#   docker build --file platform/backend/Dockerfile --tag edify-gateway platform
#
# The binary contains no migration code and the image holds no configuration:
# every setting, including the database URL, arrives through the environment
# and passes the production-protection guard before a connection is opened.
FROM golang:1.27.4-alpine AS build
WORKDIR /src/backend
COPY backend/go.mod backend/go.sum ./
RUN go mod download
COPY backend/ ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/gateway ./cmd/gateway \
 && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/scheduler ./cmd/scheduler

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/gateway /gateway
COPY --from=build /out/scheduler /scheduler
USER nonroot:nonroot
ENV EDIFY_HTTP_ADDR=0.0.0.0:8090
EXPOSE 8090
ENTRYPOINT ["/gateway"]
