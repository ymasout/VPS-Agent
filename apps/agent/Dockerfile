ARG GO_BASE_IMAGE=docker.io/library/golang@sha256:383395b794dffa5b53012a212365d40c8e37109a626ca30d6151c8348d380b5f
ARG ALPINE_BASE_IMAGE=docker.io/library/alpine@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce
FROM ${GO_BASE_IMAGE} AS build
ARG VERSION=0.6.1-dev
WORKDIR /src
COPY apps/agent/go.mod ./
COPY apps/agent/ .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w -X main.version=${VERSION}" -o /out/vps-agent ./cmd/agent

FROM ${ALPINE_BASE_IMAGE}
RUN apk add --no-cache ca-certificates docker-cli docker-cli-compose
COPY --from=build /out/vps-agent /vps-agent
ENTRYPOINT ["/vps-agent"]
