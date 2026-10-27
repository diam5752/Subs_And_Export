FROM golang:1.27.3-alpine@sha256:d200d2dd76b03a99b52651fd1325aff7dcd35422c35c01bac56571b0507f3deb AS builder
WORKDIR /src
ENV CGO_ENABLED=0 GOTOOLCHAIN=local GOMAXPROCS=2
ADD --checksum=sha256:e86c49311c0c9f7e9b3b80527f0139e5739dfe28effeaa41c444dd743f0bbd7e https://codeload.github.com/caddyserver/caddy/tar.gz/72dd0fb067f6d7826c7f79907670ba4a713bfe37 /tmp/caddy.tar.gz
RUN tar -xzf /tmp/caddy.tar.gz --strip-components=1 -C /src \
    && rm /tmp/caddy.tar.gz \
    && go get golang.org/x/net@v0.60.0 github.com/go-chi/chi/v5@v5.4.0 \
    && go mod tidy
RUN go test -p 2 ./cmd/caddy ./modules/caddyhttp/reverseproxy \
    && go build -p 2 -trimpath -buildvcs=false -ldflags='-s -w -X github.com/caddyserver/caddy/v2.CustomVersion=v2.11.7-security.20261027' -o /out/caddy ./cmd/caddy
# Preserve the reviewed stock proxy UID0/volume/binding contract.
# See README.md#existing-proxy-user-context and the exact-path role exception.
FROM caddy:2.11.7-alpine@sha256:eb4d35b7452d1ab6171fbdbe8d9275b2301dad6dad92115d91e19fb9b24d510f
RUN apk upgrade --no-cache
COPY --from=builder /out/caddy /usr/bin/caddy
LABEL org.opencontainers.image.source="https://github.com/caddyserver/caddy" \
      org.opencontainers.image.revision="72dd0fb067f6d7826c7f79907670ba4a713bfe37" \
      org.opencontainers.image.version="2.11.7-security.20261027"
