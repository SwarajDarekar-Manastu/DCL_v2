# LibreOffice headless in its own container (docs/architecture/01 §5.3): legacy .doc/.ppt/.xls conversion,
# DOCX/PPTX -> PDF renditions and forced .xlsx recalculation, one soffice process per conversion.
# office_server.py serves POST /convert on 2003; the backend calls it through backend/common/office.py.
# Build context: repository root.

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-core-nogui libreoffice-writer-nogui libreoffice-calc-nogui libreoffice-impress-nogui \
        python3 fonts-dejavu fonts-liberation fonts-noto-core fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin office
USER office
WORKDIR /home/office
# Profile template copied per conversion: Calc recalculates every formula on load (OOXML and ODF), so an
# .xlsx round trip refreshes stale cached values (Route C forced recalculation).
RUN mkdir -p /home/office/lo-profile/user && printf '%s\n' \
    '<?xml version="1.0" encoding="UTF-8"?>' \
    '<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema">' \
    '<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop></item>' \
    '<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="ODFRecalcMode" oor:op="fuse"><value>0</value></prop></item>' \
    '</oor:items>' > /home/office/lo-profile/user/registrymodifications.xcu
COPY --chown=office:office backend/devops/docker/office_server.py /home/office/office_server.py
EXPOSE 2003
CMD ["python3", "/home/office/office_server.py"]
