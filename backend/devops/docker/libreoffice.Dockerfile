# LibreOffice headless in its own container (docs/architecture/01 §5.3): legacy .doc/.ppt/.xls conversion and
# forced .xlsx recalculation. unoserver listens on 2003; workers convert with
# `unoconvert --host libreoffice --port 2003 --host-location remote <in> <out>` (unoserver client, XML-RPC).

FROM debian:bookworm-slim
ARG UNOSERVER_VERSION=3.7
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-core-nogui libreoffice-writer-nogui libreoffice-calc-nogui libreoffice-impress-nogui \
        python3 python3-uno python3-pip fonts-dejavu fonts-liberation fonts-noto-core fonts-noto-cjk \
    && pip3 install --no-cache-dir --break-system-packages "unoserver==${UNOSERVER_VERSION}" \
    && apt-get purge -y python3-pip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin office
USER office
WORKDIR /home/office
EXPOSE 2003
CMD ["unoserver", "--interface", "0.0.0.0", "--port", "2003", "--uno-interface", "127.0.0.1", "--uno-port", "2002"]
