FROM golang:1.27.3-alpine@sha256:d200d2dd76b03a99b52651fd1325aff7dcd35422c35c01bac56571b0507f3deb AS gosu-builder
WORKDIR /src
ENV CGO_ENABLED=0 GOTOOLCHAIN=local GOMAXPROCS=2
ADD --checksum=sha256:2b70da8a5480fafedc16bb1fc91b572f064d03df736cbd91a616af2f1b66ab51 https://codeload.github.com/tianon/gosu/tar.gz/29b939aa5bd4dc588af765b8248f6e39150d2565 /tmp/gosu.tar.gz
RUN tar -xzf /tmp/gosu.tar.gz --strip-components=1 -C /src \
    && rm /tmp/gosu.tar.gz \
    && go get golang.org/x/sys@v0.44.0 \
    && go mod tidy \
    && go test -p 2 ./... \
    && go build -p 2 -trimpath -buildvcs=false -ldflags='-s -w' -o /out/gosu .

FROM pgvector/pgvector:pg16@sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a AS pgvector-security
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
ENV GOSU_VERSION=1.20
COPY --from=gosu-builder --chown=0:0 --chmod=0755 /out/gosu /usr/local/bin/gosu
LABEL org.opencontainers.image.source="https://github.com/pgvector/pgvector" \
      org.opencontainers.image.version="16.15-vector0.8.7-security.20261027" \
      gr.ascentia.security.gosu.source="29b939aa5bd4dc588af765b8248f6e39150d2565" \
      gr.ascentia.security.gosu.go="1.27.3"

FROM postgres:16.15-alpine3.24@sha256:0cefaabd882e42bcb2a2f3dc56d3ce4770560ba62fd7f197f1a2e008fd5731ab AS postgres-alpine-security
RUN apk upgrade --no-cache
ENV GOSU_VERSION=1.20
COPY --from=gosu-builder --chown=0:0 --chmod=0755 /out/gosu /usr/local/bin/gosu
LABEL org.opencontainers.image.source="https://github.com/docker-library/postgres" \
      org.opencontainers.image.version="16.15-security.20261027" \
      gr.ascentia.security.gosu.source="29b939aa5bd4dc588af765b8248f6e39150d2565" \
      gr.ascentia.security.gosu.go="1.27.3"
