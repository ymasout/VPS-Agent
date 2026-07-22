FROM golang:1.23-alpine AS build
ARG VERSION=0.4.2-dev
WORKDIR /src
COPY apps/agent/go.mod ./
COPY apps/agent/ .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w -X main.version=${VERSION}" -o /out/vps-agent ./cmd/agent

FROM alpine:3.22
RUN apk add --no-cache ca-certificates docker-cli docker-cli-compose
COPY --from=build /out/vps-agent /vps-agent
ENTRYPOINT ["/vps-agent"]
