FROM golang:1.23-alpine AS build
WORKDIR /src
COPY apps/agent/go.mod ./
COPY apps/agent/ .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/vps-agent ./cmd/agent

FROM alpine:3.22
RUN apk add --no-cache ca-certificates docker-cli
COPY --from=build /out/vps-agent /vps-agent
ENTRYPOINT ["/vps-agent"]
