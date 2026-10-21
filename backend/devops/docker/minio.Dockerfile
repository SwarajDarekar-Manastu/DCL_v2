# MinIO built from the archived upstream source at a pinned tag (decision in docs/architecture/09 §H.1):
# official images are no longer published. A maintained S3-compatible replacement is chosen before M6.
# The build refuses to continue unless the tag resolves to the expected commit.

FROM golang:1.24-bookworm AS build
ARG MINIO_TAG=RELEASE.2025-10-15T17-29-55Z
ARG MINIO_COMMIT=9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a
WORKDIR /src
RUN git clone --depth 1 --branch "${MINIO_TAG}" https://github.com/minio/minio.git . \
    && test "$(git rev-parse HEAD)" = "${MINIO_COMMIT}"
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    release_time="$(echo "${MINIO_TAG}" | sed -E 's/RELEASE\.([0-9-]+)T([0-9]+)-([0-9]+)-([0-9]+)Z/\1T\2:\3:\4Z/')" \
    && CGO_ENABLED=0 go build -tags kqueue -trimpath \
        --ldflags "$(go run buildscripts/gen-ldflags.go "${release_time}")" -o /out/minio

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin minio \
    && mkdir -p /data && chown minio:minio /data
COPY --from=build /out/minio /usr/local/bin/minio
USER minio
EXPOSE 9000 9001
ENTRYPOINT ["/usr/local/bin/minio"]
CMD ["server", "/data", "--address", ":9000", "--console-address", ":9001"]
