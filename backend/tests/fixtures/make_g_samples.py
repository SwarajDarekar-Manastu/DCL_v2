"""Generate the Route G sample set: one normal and several edge-case files per supported type.

Standard library only. Output (git-ignored): ``data/samples/G/synthetic/<type>/``, a local
``data/samples/G/MANIFEST.yaml`` that also lists the ``corpus/`` and ``web/`` files when present, and the
committed template ``backend/tests/fixtures/g_samples.template.yaml`` (no real file names).

Types (docs/architecture/03 §11): zip, tar, tar.gz/tgz, gz, wbpz, stl, step/stp, igs/iges, scdoc, dwg.
``expect`` lines are written from the manual, not from what the route does today: they say what the manual
requires, so a failing check shows a route defect or a manual gap, not a changed test.

``web/`` files are compatibility checks only (public CAD of no relevance to our domain); ``corpus/``
files are real copies from the OneDrive registry; ``synthetic/`` is fictitious and byte-stable.

Run: ``uv run python backend/tests/fixtures/make_g_samples.py``
"""

import gzip
import hashlib
import io
import json
import math
import shutil
import struct
import tarfile
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SAMPLES = ROOT / "data" / "samples" / "G"
OUT = SAMPLES / "synthetic"
TEMPLATE = Path(__file__).resolve().parent / "g_samples.template.yaml"
STAMP = (2026, 1, 1, 0, 0, 0)

CASES: list[dict] = []


def add(rel: str, data: bytes, kind: str, covers: str, expect: str, route: str = "G") -> None:
    path = OUT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    CASES.append(
        {
            "path": f"synthetic/{rel}",
            "origin": "synthetic",
            "kind": kind,
            "route": route,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "covers": covers,
            "expect": expect,
        }
    )


def png(width: int, height: int, shade) -> bytes:
    rows = b"".join(b"\0" + b"".join(bytes(shade(x, y)) for x in range(width)) for y in range(height))

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows, 9))
        + chunk(b"IEND", b"")
    )


def zip_of(members, method=zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", method) as z:
        for name, data in members:
            info = zipfile.ZipInfo(name, STAMP)
            info.compress_type = method
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
    return buffer.getvalue()


def tar_of(members, mode="w", links=()) -> bytes:
    if mode == "w:gz":
        return gz(tar_of(members, "w", links))
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode=mode, format=tarfile.GNU_FORMAT) as t:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            t.addfile(info, io.BytesIO(data))
        for name, kind, target in links:
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE
            info.linkname, info.mtime = target, 0
            t.addfile(info)
    return buffer.getvalue()


def gz(data: bytes) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", fileobj=buffer, mode="wb", mtime=0) as g:
        g.write(data)
    return buffer.getvalue()


# ---- fictitious content ---------------------------------------------------------------------------
README = (
    b"# Cold-flow bundle (synthetic)\n\nChannels, a fit script and a plot from a fictitious injector run.\n"
)
CHANNELS = "time_s,pressure_bar,flow_g_s\n" + "".join(
    f"{i * 0.1:.1f},{10 + 0.05 * i:.2f},{50 + 0.2 * i:.1f}\n" for i in range(40)
)
SCRIPT = b'"""Fit discharge coefficient (synthetic)."""\n\n\ndef cd(flow, area, rho, dp):\n    return flow / (area * (2 * rho * dp) ** 0.5)\n'  # noqa: E501 (fixture content is one literal)
NOTE = b"Run 7: pressure stable after 1.2 s. Valve V3 chattered once. Check the log.\n"
PLOT = png(48, 32, lambda x, y: (x * 5 % 256, y * 7 % 256, 128))


def bundle() -> list[tuple[str, bytes]]:
    return [
        ("readme.md", README),
        ("data/channels.csv", CHANNELS.encode()),
        ("scripts/fit_cd.py", SCRIPT),
        ("figures/plot.png", PLOT),
        ("notes/run7.txt", NOTE),
        (".DS_Store", b"\0\0\0\1Bud1" + b"\0" * 32),
        ("Thumbs.db", b"\xd0\xcf\x11\xe0" + b"\0" * 32),
    ]


def _crc_update(crc: int, byte: int) -> int:
    crc ^= byte
    for _ in range(8):
        crc = (crc >> 1) ^ (0xEDB88320 if crc & 1 else 0)
    return crc


def zipcrypto(data: bytes, crc: int, password: bytes = b"x") -> bytes:
    """Traditional PKWARE encryption with a fixed header, so the output is byte-stable."""
    keys = [0x12345678, 0x23456789, 0x34567890]

    def update(byte: int) -> None:
        keys[0] = _crc_update(keys[0], byte)
        keys[1] = ((keys[1] + (keys[0] & 0xFF)) * 134775813 + 1) & 0xFFFFFFFF
        keys[2] = _crc_update(keys[2], keys[1] >> 24)

    for byte in password:
        update(byte)
    out = bytearray()
    for byte in bytes(range(11)) + bytes([crc >> 24]) + data:
        t = (keys[2] | 2) & 0xFFFF
        out.append(byte ^ (((t * (t ^ 1)) >> 8) & 0xFF))
        update(byte)
    return bytes(out)


def encrypted_zip() -> bytes:
    plain = b"The thrust curve is in the other file.\n"
    crc = zlib.crc32(plain)
    raw = bytearray(zip_of([("secret.txt", zipcrypto(plain, crc))], zipfile.ZIP_STORED))
    raw[6] |= 1
    struct.pack_into("<I", raw, 14, crc)
    central = raw.rfind(b"PK\x01\x02")
    raw[central + 8] |= 1
    struct.pack_into("<I", raw, central + 16, crc)
    return bytes(raw)


def declared(sizes: list[int]) -> bytes:
    """Stored zip whose headers declare ``sizes`` (bytes); the real payload is 16 bytes each. Tests that "
    "the guard reads declared sizes first."""
    raw = bytearray(zip_of([(f"part{i}.bin", bytes(16)) for i in range(len(sizes))], zipfile.ZIP_STORED))
    for i, size in enumerate(sizes):
        local = raw.find(f"part{i}.bin".encode()) - 30
        struct.pack_into("<II", raw, local + 18, size, size)
    cd = raw.find(b"PK\x01\x02")
    for size in sizes:
        struct.pack_into("<II", raw, cd + 20, size, size)
        cd = raw.find(b"PK\x01\x02", cd + 4)
    return bytes(raw)


def zip_cases() -> None:
    add(
        "zip/normal_cold_flow_bundle.zip",
        zip_of(bundle()),
        "normal",
        "a typical bundle: csv, md, py, png, txt plus .DS_Store and Thumbs.db",
        "Route G; archive document lists 7 members; the two junk members are skipped by the gate; the 5 "
        "others become blobs and documents (archive_member); status ACTIVE",
    )
    inner = zip_of([("data/channels.csv", CHANNELS.encode()), ("notes/run7.txt", NOTE)])
    add(
        "zip/normal_zip_in_zip.zip",
        zip_of([("readme.md", README), ("inner/run7_data.zip", inner)]),
        "normal",
        "one level of nesting (depth 2, allowed)",
        "Route G; inner archive expanded in place, members named outer/inner.zip!/member; no flag",
    )
    add(
        "zip/edge_duplicate_member_case.zip",
        zip_of([("Report.txt", b"upper\n"), ("report.txt", b"lower\n"), ("REPORT.TXT", b"all caps\n")]),
        "edge",
        "same name in different case (manual edge case: duplicate member names in different case)",
        "three distinct members, none overwritten; three different blobs",
    )
    junk = [
        (f"env/Lib/site-packages/pkg_{i:03d}/mod_{j}.py", b"x = 1\n") for i in range(60) for j in range(5)
    ]
    junk += [
        (f"env/Lib/site-packages/pkg_{i:03d}/__pycache__/mod_0.cpython-311.pyc", b"\0" * 16)
        for i in range(60)
    ]
    add(
        "zip/edge_mostly_junk_python_env.zip",
        zip_of(junk + [("README.md", README), ("analysis/run_fit.py", SCRIPT)]),
        "edge",
        "a whole Python environment (manual edge case): 98 % of members hit the Tier-1 gate",
        "Route G; archive marked mostly_junk in the catalog (> 90 % skipped); only README.md and "
        "run_fit.py kept",
    )
    add(
        "zip/edge_encrypted.zip",
        encrypted_zip(),
        "edge",
        "password-protected member",
        "PARSE_FAILURE HARD (encrypted archive, manual step 7); nothing extracted",
    )
    add(
        "zip/edge_empty.zip",
        b"PK\x05\x06" + b"\0" * 18,
        "edge",
        "valid zip with no entries",
        "Route G; zero members; archive document exists; no crash, no flag or a soft note",
    )
    add(
        "zip/edge_truncated.zip",
        zip_of(bundle())[:-120],
        "edge",
        "central directory cut off",
        "PARSE_FAILURE HARD (unreadable archive) with the partial manifest if any",
    )
    add(
        "zip/edge_unicode_names.zip",
        zip_of(
            [
                ("Prüfbericht_Düse_№3 (Überdruck).txt", NOTE),
                ("測試記錄.csv", CHANNELS.encode()),
                ("with space/ file .py", SCRIPT),
                (".hidden_notes.md", README),
            ]
        ),
        "edge",
        "non-ASCII, spaces, leading dot in member names",
        "all four members listed with their exact names; member paths survive into derived blobs",
    )
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as z:
        z.writestr(zipfile.ZipInfo("readme.md", STAMP), README)
        link = zipfile.ZipInfo("latest_run", STAMP)
        link.external_attr = 0o120777 << 16
        z.writestr(link, "data/channels.csv")
    add(
        "zip/edge_symlink_member.zip",
        raw.getvalue(),
        "edge",
        "symlink entry (manual: symlinks ignored)",
        "symlink member skipped with a reason; readme.md kept; never followed",
    )
    add(
        "zip/edge_declared_1p1GiB_member.zip",
        declared([int(1.1 * 1024**3)]),
        "edge",
        "header declares a 1.1 GiB member (stored, ratio 1); payload is 16 bytes",
        "member held, not read: HELD_LARGE_FILE SOFT per held member; archive itself still "
        "ACTIVE_WITH_SOFT_FLAGS",
    )
    add(
        "zip/edge_declared_total_over_5GiB.zip",
        declared([3 * 1024**3, 3 * 1024**3]),
        "edge",
        "two members declare 3 GiB each (6 GiB total)",
        "PARSE_FAILURE HARD (total uncompressed above 5 GB) before any extraction",
    )
    add(
        "zip/edge_over_50000_entries.zip",
        zip_of([(f"files/f{i:05d}.txt", b"") for i in range(50_001)]),
        "edge",
        "50,001 entries",
        "PARSE_FAILURE HARD (entries above 50,000) with the manifest so far",
    )
    add(
        "zip/EDGE_UPPERCASE_EXTENSION.ZIP",
        zip_of(bundle()[:2]),
        "edge",
        "upper-case extension",
        "Route G exactly as for a lower-case .zip",
    )


def tar_cases() -> None:
    members = [(n, d) for n, d in bundle()]
    add(
        "tar/normal_cold_flow_bundle.tar",
        tar_of(members),
        "normal",
        "plain tar",
        "Route G; same 7 members as the zip; junk skipped",
    )
    add(
        "tar/normal_cold_flow_bundle.tar.gz",
        tar_of(members, "w:gz"),
        "normal",
        ".tar.gz",
        "Route G; same members",
    )
    add(
        "tar/normal_cold_flow_bundle.tar.bz2",
        tar_of(members, "w:bz2"),
        "normal",
        ".tar.bz2 (supported by the code, not in the inventory)",
        "Route G; same members",
    )
    add(
        "tar/normal_cold_flow_bundle.tar.xz",
        tar_of(members, "w:xz"),
        "normal",
        ".tar.xz (supported by the code, not in the inventory)",
        "Route G; same members",
    )
    add(
        "tar/normal_cold_flow_bundle.tgz",
        tar_of(members, "w:gz"),
        "normal",
        ".tgz spelling",
        "Route G; identical to .tar.gz",
    )
    add(
        "tar/edge_symlink_and_hardlink.tar",
        tar_of(
            members[:2],
            links=[("latest", "symlink", "data/channels.csv"), ("copy.csv", "hardlink", "data/channels.csv")],
        ),
        "edge",
        "symlink and hardlink members (manual: symlinks in tar ignored)",
        "links skipped, never followed; the two regular members kept",
    )
    add(
        "tar/edge_absolute_path.tar",
        tar_of([("/etc/dcl_probe.txt", b"x\n"), ("readme.md", README)]),
        "edge",
        "absolute path member",
        "PARSE_FAILURE HARD (path traversal) with the manifest; nothing written outside scratch",
    )
    add(
        "tar/edge_dotdot_path.tar.gz",
        tar_of([("../outside.txt", b"x\n"), ("readme.md", README)], "w:gz"),
        "edge",
        "../ member",
        "PARSE_FAILURE HARD (path traversal)",
    )
    add(
        "tar/edge_truncated.tar.gz",
        tar_of(members, "w:gz")[:-300],
        "edge",
        "gzip stream cut off",
        "PARSE_FAILURE HARD (unreadable archive)",
    )
    add(
        "tar/edge_empty.tar",
        b"\0" * 1024,
        "edge",
        "tar with only end-of-archive blocks",
        "Route G; zero members; no crash",
    )
    add(
        "tar/edge_tgz_is_really_zip.tgz",
        zip_of(members[:2]),
        "edge",
        "name says .tgz, content is a zip",
        "content wins (manual 1.1): the file is read as the archive type it really is, or fails with "
        "PARSE_FAILURE; never a crash",
    )


def gz_cases() -> None:
    add(
        "gz/normal_channels.csv.gz",
        gz(CHANNELS.encode()),
        "normal",
        "single gzip of a csv",
        "Route G gunzips; member channels.csv becomes a blob and goes to Route C",
    )
    add(
        "gz/normal_run_notes.txt.gz",
        gz(NOTE),
        "normal",
        "single gzip of text",
        "Route G gunzips; member run_notes.txt",
    )
    add(
        "gz/edge_empty_payload.csv.gz",
        gz(b""),
        "edge",
        "gzip of an empty file",
        "member skipped as empty; no crash",
    )
    add(
        "gz/edge_double_gzip.csv.gz.gz",
        gz(gz(CHANNELS.encode())),
        "edge",
        "gzip inside gzip (depth 2)",
        "both layers removed within the nesting limit; member channels.csv",
    )
    add(
        "gz/edge_multi_member.csv.gz",
        gz(CHANNELS.encode()) + gz(b"90.0,99.9,1.0\n"),
        "edge",
        "two gzip members concatenated (legal)",
        "payload is the concatenation of both members",
    )
    add(
        "gz/edge_trailing_garbage.csv.gz",
        gz(CHANNELS.encode()) + b"\0\0\0\0garbage",
        "edge",
        "bytes after the gzip stream",
        "either the csv is recovered or PARSE_FAILURE HARD; never a crash",
    )
    add(
        "gz/edge_truncated.csv.gz",
        gz(CHANNELS.encode() * 20)[:-40],
        "edge",
        "stream cut off",
        "PARSE_FAILURE HARD (unreadable)",
    )
    add(
        "gz/edge_not_gzip_named_gz.gz",
        b"time_s,pressure_bar\n0.0,10.0\n",
        "edge",
        "plain text with a .gz name",
        "content wins: not an archive; falls to the type of its content (csv, Route C)",
        route="C",
    )
    add(
        "gz/edge_zip_named_gz.gz",
        zip_of([("readme.md", README)]),
        "edge",
        "zip content under a .gz name",
        "content wins: read as zip",
    )
    add(
        "negative/junk_Test_plan.synctex.gz",
        gz(b"SyncTeX Version:1\nInput:1:./main.tex\n" * 50),
        "negative",
        "LaTeX synctex output (gate Tier 2 ending .synctex.gz)",
        "never reaches Route G: SKIPPED_JUNK at the gate",
        route="gate",
    )


# ---- wbpz (ANSYS Workbench package: a zip) ----------------------------------------------------------
def solver_log(nodes=2012, elements=1840, converged=True, warnings=2, errors=0) -> bytes:
    lines = [
        " ANSYS Mechanical Enterprise",
        "",
        " Release: 2019 R1.2          Build: 19.3       Platform: WINDOWS x64",
        "",
    ]
    lines += [f"...Number of elements: {elements}", f"...Number of nodes:    {nodes}", ""]
    lines += [" TERMINATE ANALYSIS IF NOT CONVERGED . . . . . .YES (EXIT)", ""]
    for i in range(1, 4):
        lines.append(
            f"   SUBSTEP {i}: FORCE CONVERGENCE VALUE  =  0.{9 - i}E-0{3 + i}  CRITERION=  0.3124E-03"
            + (" <<< CONVERGED" if converged or i < 3 else "")
        )
    lines += ["", " *** WARNING ***" + " " * 25 + "CP =       0.359   TIME= 12:01:59"] * warnings
    lines += [
        " *** ERROR ***" + " " * 27 + "CP =       4.100   TIME= 12:02:30",
        " Element 411 has become highly distorted.",
    ] * errors
    if converged:
        lines += ["", " >>> SOLUTION CONVERGED AFTER EQUILIBRIUM ITERATION   8"]
    else:
        lines += [
            "",
            " *** NOTE ***",
            " The solution did NOT converge: NOT CONVERGED after 25 equilibrium iterations.",
        ]
    lines += [
        "",
        " Total CPU time for main thread                    :       12.5 seconds",
        " Elapsed time spent solution - preprocessing       :        0.4 seconds",
        " Elapsed time spent solution - solve               :        9.7 seconds",
        "",
    ]
    return "\n".join(lines).encode()


def matml(
    materials=(
        (
            "Structural Steel (synthetic)",
            (
                ("Density", "7850", "kg", "m", -3),
                ("Young's Modulus", "2.0E+11", "Pa", None, 1),
                ("Poisson's Ratio", "0.3", None, None, 1),
            ),
        ),
    ),
) -> bytes:
    body, details, n = [], [], 0
    for name, props in materials:
        data = []
        for prop, value, u1, u2, power in props:
            n += 1
            units = ""
            if u1:
                units = (
                    f'<Units name="{u1}"><Unit><Name>{u1}</Name></Unit>'
                    + (f'<Unit power="{power}"><Name>{u2}</Name></Unit>' if u2 else "")
                    + "</Units>"
                )
            data.append(
                f'<PropertyData property="pr{n}"><Data format="string">-</Data><ParameterValue parameter="pa{n}" format="float"><Data format="string">{value}</Data></ParameterValue></PropertyData>'  # noqa: E501 (fixture content is one literal)
            )
            details.append(
                f'<PropertyDetails id="pr{n}"><Name>{prop}</Name></PropertyDetails><ParameterDetails id="pa{n}"><Name>{prop}</Name>{units}</ParameterDetails>'  # noqa: E501 (fixture content is one literal)
            )
        body.append(f"<Material><BulkDetails><Name>{name}</Name>{''.join(data)}</BulkDetails></Material>")
    return (
        '<?xml version="1.0" encoding="utf-8"?><MatML_Doc>'
        + "".join(body)
        + "<Metadata>"
        + "".join(details)
        + "</Metadata></MatML_Doc>"
    ).encode()


def wbpj(systems=("Engineering Data", "Geometry", "Mesh", "Static Structural")) -> bytes:
    items = "".join(f'<Container name="{s}" />\n' for s in systems)
    return (
        '﻿<?xml version="1.0" encoding="utf-8"?>\n<Storage>\n  <Project Version="9.1">\n    '
        '<framework-build-version valType="String">19.3.111.0</framework-build-version>\n'
        + items
        + "  </Project>\n</Storage>\n"
    ).encode("utf-8")


MESH_PNG = png(64, 48, lambda x, y: (40, (x * 4) % 256, 200))
STRESS_PNG = png(64, 48, lambda x, y: ((x * 4) % 256, 60, (y * 5) % 256))


def wbpz_members(log=True, mat=True, project=True, images=True):
    base = "Study_files/dp0/SYS/MECH/"
    out = []
    if project:
        out.append(("Study.wbpj", wbpj()))
    if log:
        out.append((base + "solve.out", solver_log()))
    if mat:
        out.append((base + "MatML.xml", matml()))
    if images:
        out += [(base + "Mesh.png", MESH_PNG), (base + "Equivalent_Stress.png", STRESS_PNG)]
    return out


def wbpz_cases() -> None:
    add(
        "wbpz/normal_oring_study.wbpz",
        zip_of(wbpz_members()),
        "normal",
        "complete package: project file, solver log, material XML, two result images",
        "Route G indexes it inside (manual step 5): solver table (ANSYS Mechanical, 1840 elements, 2012 "
        "nodes, converged, CPU 12.5 s), material Structural Steel with density 7850 kg m^-3 and Young's "
        "modulus 2.0E+11 Pa as table nodes and material mentions, analysis systems in documents.catalog, "
        "the two PNGs handed over to the figure pipeline; solve.out kept despite the .out junk ending "
        "(kept_endings_by_parent_kind)",
    )
    add(
        "wbpz/edge_no_solver_log.wbpz",
        zip_of(wbpz_members(log=False)),
        "edge",
        "geometry and materials but never solved",
        "Route G; materials and systems indexed; no solver table; no failure",
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in wbpz_members(log=False):
            info = zipfile.ZipInfo(name, STAMP)
            z.writestr(info, data)
        z.writestr(
            zipfile.ZipInfo("Study_files/dp0/SYS/MECH/solve.out", STAMP),
            solver_log(converged=False, warnings=5, errors=2),
        )
    add(
        "wbpz/edge_not_converged_with_errors.wbpz",
        buffer.getvalue(),
        "edge",
        "solver log with NOT CONVERGED, ERROR and WARNING lines",
        "solver table shows converged = no (final NOT CONVERGED statement) and lists the warnings and "
        "errors; the problems are visible in the document, not buried",
    )
    broken = matml()[:-120]
    members = [(n, broken if n.endswith("MatML.xml") else d) for n, d in wbpz_members()]
    add(
        "wbpz/edge_broken_matml.wbpz",
        zip_of(members),
        "edge",
        "material XML cut off mid-element",
        "no material nodes for the broken file, the rest of the package still indexed; no crash",
    )
    add(
        "wbpz/edge_only_project_file.wbpz",
        zip_of([("Study.wbpj", wbpj())]),
        "edge",
        "project file only",
        "systems recorded in the catalog; nothing else",
    )
    add(
        "wbpz/edge_not_a_zip.wbpz",
        bytes(range(256)) * 8,
        "edge",
        "random bytes with a .wbpz name",
        "PARSE_FAILURE HARD (unreadable file)",
    )
    add(
        "wbpz/edge_empty_file.wbpz",
        b"",
        "edge",
        "zero bytes",
        "dropped by the gate as empty, or PARSE_FAILURE HARD; never a crash",
    )
    add(
        "wbpz/edge_encrypted.wbpz",
        encrypted_zip(),
        "edge",
        "password-protected package",
        "PARSE_FAILURE HARD (encrypted archive)",
    )


# ---- meshes and B-reps -------------------------------------------------------------------------------
def quad(a, b, c, d):
    return [(a, b, c), (a, c, d)]


def box_mesh(x0, y0, z0, dx, dy, dz):
    p = [(x0 + (k & 1) * dx, y0 + ((k >> 1) & 1) * dy, z0 + ((k >> 2) & 1) * dz) for k in range(8)]
    faces = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    return [tuple(p[i] for i in t) for f in faces for t in quad(*f)]


def cylinder_mesh(radius, height, segments=64):
    tris = []
    ring = [
        (radius * math.cos(2 * math.pi * i / segments), radius * math.sin(2 * math.pi * i / segments))
        for i in range(segments)
    ]
    for i in range(segments):
        (x1, y1), (x2, y2) = ring[i], ring[(i + 1) % segments]
        tris += quad((x1, y1, 0), (x2, y2, 0), (x2, y2, height), (x1, y1, height))
        tris.append(((0, 0, 0), (x2, y2, 0), (x1, y1, 0)))
        tris.append(((0, 0, height), (x1, y1, height), (x2, y2, height)))
    return tris


def sphere_mesh(radius, rings, sectors):
    def at(i, j):
        phi, theta = math.pi * i / rings, 2 * math.pi * j / sectors
        return (
            radius * math.sin(phi) * math.cos(theta),
            radius * math.sin(phi) * math.sin(theta),
            radius * math.cos(phi),
        )

    tris = []
    for i in range(rings):
        for j in range(sectors):
            a, b, c, d = at(i, j), at(i + 1, j), at(i + 1, j + 1), at(i, j + 1)
            if i:
                tris.append((a, b, d))
            if i < rings - 1:
                tris.append((b, c, d))
    return tris


def normal_of(t):
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = t
    ux, uy, uz, vx, vy, vz = bx - ax, by - ay, bz - az, cx - ax, cy - ay, cz - az
    n = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
    length = math.sqrt(sum(c * c for c in n)) or 1.0
    return tuple(c / length for c in n)


def stl_binary(tris, header=b"synthetic binary STL (units: mm)") -> bytes:
    out = bytearray(header.ljust(80, b" ")[:80] + struct.pack("<I", len(tris)))
    for t in tris:
        out += struct.pack("<12fH", *normal_of(t), *t[0], *t[1], *t[2], 0)
    return bytes(out)


def stl_ascii(tris, name="synthetic") -> bytes:
    lines = [f"solid {name}"]
    for t in tris:
        nx, ny, nz = normal_of(t)
        lines += (
            [f"  facet normal {nx:e} {ny:e} {nz:e}", "    outer loop"]
            + [f"      vertex {x:e} {y:e} {z:e}" for x, y, z in t]
            + ["    endloop", "  endfacet"]
        )
    lines.append(f"endsolid {name}")
    return ("\n".join(lines) + "\n").encode()


def stl_cases() -> None:
    cube = box_mesh(0, 0, 0, 20, 20, 20)
    cylinder = cylinder_mesh(5, 30)
    add(
        "stl/normal_ascii_cube_20mm.stl",
        stl_ascii(cube, "cube20"),
        "normal",
        "ASCII STL, closed cube",
        "Route G cad_reference with trimesh measurement: bounding box 20 × 20 × 20, volume 8000, surface "
        "area 2400 (model units, STL carries none: stated), 12 triangles, watertight, 1 body",
    )
    add(
        "stl/normal_binary_cylinder_r5_h30.stl",
        stl_binary(cylinder),
        "normal",
        "binary STL, closed cylinder (64 segments)",
        "measurement: bounding box about 10 × 10 × 30, volume about 2352 (a 64-sided prism of radius 5, "
        "height 30; a true circle would give 2356), 256 triangles, watertight, 1 body",
    )
    add(
        "stl/edge_open_box_not_watertight.stl",
        stl_binary(cube[:-2]),
        "edge",
        "one face missing",
        "measured; volume marked approximate (mesh not watertight); watertight false",
    )
    add(
        "stl/edge_two_disjoint_bodies.stl",
        stl_binary(box_mesh(0, 0, 0, 10, 10, 10) + box_mesh(50, 0, 0, 10, 10, 10)),
        "edge",
        "two separate cubes in one file",
        "measured; bodies = 2; bounding box 60 × 10 × 10",
    )
    add(
        "stl/edge_binary_header_starts_with_solid.stl",
        stl_binary(cylinder, b"solid exported by a CAD tool that wrote ASCII words into a binary header"),
        "edge",
        "binary STL whose 80-byte header starts with 'solid' (a classic mis-detection)",
        "read as binary: same measurement as the normal cylinder; not treated as ASCII and failed",
    )
    add(
        "stl/edge_header_only_zero_triangles.stl",
        struct.pack("<80sI", b"empty", 0),
        "edge",
        "valid binary STL with zero triangles",
        "no geometry: the document is recorded with a note or PARSE_FAILURE; no crash, no division by zero",
    )
    add(
        "stl/edge_truncated_binary.stl",
        stl_binary(cylinder)[: 84 + 50 * 40],
        "edge",
        "header says 384 triangles, file holds 40",
        "PARSE_FAILURE HARD (unreadable file) or measured from the triangles present with a flag; never "
        "silent",
    )
    add(
        "stl/edge_ascii_with_nan_vertices.stl",
        stl_ascii(cube[:6], "nan").replace(b"0.000000e+00", b"nan", 3),
        "edge",
        "NaN coordinates",
        "no NaN in the recorded numbers (bounding box, volume); failure or a flag instead",
    )
    add(
        "stl/edge_degenerate_zero_area.stl",
        stl_binary([((0, 0, 0), (1, 1, 1), (2, 2, 2))] * 12),
        "edge",
        "all triangles are collinear (zero area)",
        "no geometry or zero volume stated honestly; no crash",
    )
    add(
        "stl/EDGE_UPPERCASE_EXTENSION.STL",
        stl_ascii(cube, "cube20"),
        "edge",
        "upper-case extension",
        "treated exactly like .stl",
    )
    add(
        "stl/edge_large_mesh_about_200k_triangles.stl",
        stl_binary(sphere_mesh(25, 316, 316)),
        "edge",
        "about 10 MB mesh for time and memory",
        "measured within the cpu_parse time limit and 6 GiB; volume about 65450 (sphere radius 25, within "
        "1 %)",
    )


def step_text(solids, units="MILLI") -> bytes:
    lines = []

    def ent(text):
        lines.append(text)
        return f"#{len(lines)}"

    mm = ent(f"( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.{units}.,.METRE.) )")
    angle = ent("( NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.) )")
    solid_angle = ent("( NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT() )")
    accuracy = ent(
        f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-07),{mm},'distance_accuracy_value','confusion accuracy')"  # noqa: E501 (fixture content is one literal)
    )
    context = ent(
        f"( GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT(({accuracy})) GLOBAL_UNIT_ASSIGNED_CONTEXT(({mm},{angle},{solid_angle})) REPRESENTATION_CONTEXT('ID1','3D') )"  # noqa: E501 (fixture content is one literal)
    )
    dirs = [ent("DIRECTION('',(1.,0.,0.))"), ent("DIRECTION('',(0.,1.,0.))"), ent("DIRECTION('',(0.,0.,1.))")]
    origin = ent("CARTESIAN_POINT('',(0.,0.,0.))")
    world = ent(f"AXIS2_PLACEMENT_3D('',{origin},{dirs[2]},{dirs[0]})")
    breps = []
    for label, (ox, oy, oz), size in solids:
        verts = {}
        for k in range(8):
            point = ent(
                f"CARTESIAN_POINT('',({ox + (k & 1) * size[0]:.6f},{oy + ((k >> 1) & 1) * size[1]:.6f},{oz + ((k >> 2) & 1) * size[2]:.6f}))"  # noqa: E501 (fixture content is one literal)
            )
            verts[k] = (ent(f"VERTEX_POINT('',{point})"), point)
        edges = {}
        for a in range(8):
            for axis in range(3):
                if not a & (1 << axis):
                    b = a | (1 << axis)
                    vector = ent(f"VECTOR('',{dirs[axis]},{size[axis]:.6f})")
                    line = ent(f"LINE('',{verts[a][1]},{vector})")
                    edges[(a, b)] = ent(f"EDGE_CURVE('',{verts[a][0]},{verts[b][0]},{line},.T.)")
        faces = []
        for axis in range(3):
            u, v = (axis + 1) % 3, (axis + 2) % 3
            for side in (0, 1):
                loop = [(side << axis) | (cu << u) | (cv << v) for cu, cv in ((0, 0), (1, 0), (1, 1), (0, 1))]
                if side == 0:
                    loop.reverse()
                oriented = []
                for a, b in zip(loop, loop[1:] + loop[:1], strict=True):
                    sense = ".T." if a < b else ".F."
                    oriented.append(
                        ent("ORIENTED_EDGE('',*,*," + edges[(min(a, b), max(a, b))] + "," + sense + ")")
                    )
                edge_loop = ent("EDGE_LOOP('',(" + ",".join(oriented) + "))")
                bound = ent("FACE_OUTER_BOUND(''," + edge_loop + ",.T.)")
                normal = [0.0, 0.0, 0.0]
                normal[axis] = 1.0 if side else -1.0
                direction = ent(f"DIRECTION('',({normal[0]:.1f},{normal[1]:.1f},{normal[2]:.1f}))")
                placement = ent(
                    "AXIS2_PLACEMENT_3D(''," + verts[loop[0]][1] + "," + direction + "," + dirs[u] + ")"
                )
                plane = ent("PLANE(''," + placement + ")")
                faces.append(ent("ADVANCED_FACE('',(" + bound + ")," + plane + ",.T.)"))
        shell = ent("CLOSED_SHELL('',(" + ",".join(faces) + "))")
        breps.append(ent("MANIFOLD_SOLID_BREP('" + label + "'," + shell + ")"))
    shape = ent(f"ADVANCED_BREP_SHAPE_REPRESENTATION('',({world},{','.join(breps)}),{context})")
    app = ent("APPLICATION_CONTEXT('core data for automotive mechanical design processes')")
    ent("APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000," + app + ")")
    mechanical = ent("MECHANICAL_CONTEXT(''," + app + ",'mechanical')")
    product = ent("PRODUCT('part','part',''," + "(" + mechanical + "))")
    formation = ent("PRODUCT_DEFINITION_FORMATION('1',''," + product + ")")
    design = ent("PRODUCT_DEFINITION_CONTEXT('part definition'," + app + ",'design')")
    definition = ent("PRODUCT_DEFINITION('design',''," + formation + "," + design + ")")
    defined_shape = ent("PRODUCT_DEFINITION_SHAPE('',''," + definition + ")")
    ent("SHAPE_DEFINITION_REPRESENTATION(" + defined_shape + "," + shape + ")")
    head = "ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('synthetic part'),'2;1');\nFILE_NAME('part.step','2026-01-01T00:00:00',('dcl'),(''),'','','');\nFILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));\nENDSEC;\nDATA;\n"  # noqa: E501 (fixture content is one literal)
    return (
        head
        + "".join(f"#{i} = {text};\n" for i, text in enumerate(lines, 1))
        + "ENDSEC;\nEND-ISO-10303-21;\n"
    ).encode()


def step_cases() -> None:
    box = step_text([("box", (0, 0, 0), (30, 20, 10))])
    add(
        "step/normal_box_30x20x10mm.step",
        box,
        "normal",
        "single closed solid, AP214, millimetres",
        "measurement: bounding box 30 × 20 × 10 mm, volume 6000 mm³, surface area 2200 mm², 1 solid; "
        "B-rep tessellated by OpenCASCADE. The solid is closed, so the volume must be reported as exact; "
        "check that the route does not call it approximate (trimesh does not merge vertices across the "
        "faces cascadio returns, so is_watertight is False for this file)",
    )
    add(
        "step/normal_box_stp_extension.stp",
        box,
        "normal",
        ".stp spelling of the same part",
        "identical measurement to the .step",
    )
    add(
        "step/edge_two_solids_one_file.step",
        step_text([("left", (0, 0, 0), (10, 10, 10)), ("right", (40, 0, 0), (10, 10, 10))]),
        "edge",
        "assembly-like file with two solids",
        "solids = 2; bounding box 50 × 10 × 10; volume 2000 mm³",
    )
    add(
        "step/edge_header_only_no_geometry.step",
        b"ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('empty'),'2;1');\nFILE_NAME('e.step','2026-01-01T00:00:0"
        b"0',(''),(''),'','','');\nFILE_SCHEMA(('AUTOMOTIVE_DESIGN'));\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-103"
        b"03-21;\n",
        "edge",
        "valid STEP with no entities",
        "no geometry: recorded with a note or PARSE_FAILURE; no crash",
    )
    add(
        "step/edge_truncated.step",
        box[: len(box) // 2],
        "edge",
        "file cut in half",
        "PARSE_FAILURE HARD (unreadable file) or measured partially with a flag; never silent",
    )
    add(
        "step/edge_text_note_named_step.step",
        b"Drawing review notes, not a CAD file.\nSee bracket_v3.pdf.\n",
        "edge",
        "plain text under a .step name",
        "PARSE_FAILURE HARD (unreadable file) with the file name and size kept",
    )
    add(
        "step/edge_centimetre_units_declared.step",
        step_text([("box_cm", (0, 0, 0), (1.0, 0.5, 0.25))], units="CENTI"),
        "edge",
        "units declared as centimetres (not millimetres)",
        "numbers reported in the file's own unit converted to mm: box 10 × 5 × 2.5 mm (1 × 0.5 × 0.25 "
        "cm); the unit is never assumed to be mm",
    )


def iges_cases() -> None:
    add("iges/edge_empty.igs", b"", "edge", "zero bytes", "dropped as empty or PARSE_FAILURE HARD; no crash")
    add(
        "iges/edge_text_named_igs.igs",
        b"Surface list for the nozzle (notes only).\n",
        "edge",
        "plain text under .igs",
        "PARSE_FAILURE HARD (unreadable file)",
    )
    source = SAMPLES / "web" / "iges" / "surf114.igs"
    if source.exists():
        add(
            "iges/edge_truncated.igs",
            source.read_bytes()[:60_000],
            "edge",
            "real IGES cut in the data section (derived from the web sample)",
            "PARSE_FAILURE HARD or partial measurement with a flag",
        )


# ---- reference-only CAD ------------------------------------------------------------------------------
def mini_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 "
        b"5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode() + b"".join(
        f"{o:010d} 00000 n \n".encode() for o in offsets
    )
    return bytes(
        out + f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )


DXF = b"0\nSECTION\n2\nENTITIES\n0\nLINE\n8\n0\n10\n0.0\n20\n0.0\n11\n100.0\n21\n50.0\n0\nENDSEC\n0\nEOF\n"


def reference_cases() -> None:
    add(
        "dwg/normal_header_only_AC1032.dwg",
        b"AC1032" + b"\0" * 7 + b"\x01" + bytes(2000),
        "normal",
        "DWG with a valid version tag (AutoCAD 2018) and no content",
        "Route G cad_reference (manual: no open parser): catalog holds file name, size, folder and link; "
        "no measurement; no flag",
    )
    add(
        "dwg/edge_zero_byte.dwg",
        b"",
        "edge",
        "zero bytes",
        "dropped as empty or recorded as reference with size 0; no crash",
    )
    add(
        "dwg/edge_text_named_dwg.dwg",
        b"Layer list: 0, WALLS, DIMS\n",
        "edge",
        "text under a .dwg name",
        "still a cad_reference by name (no parser to disagree); no crash",
    )
    add(
        "scdoc/edge_zero_byte.scdoc",
        b"",
        "edge",
        "zero bytes",
        "dropped as empty or recorded as reference; no crash",
    )
    add(
        "scdoc/edge_text_named_scdoc.scdoc",
        b"SpaceClaim export notes\n",
        "edge",
        "text under a .scdoc name",
        "cad_reference by name; no crash",
    )
    add(
        "scdoc/edge_random_binary.scdoc",
        bytes(range(256)) * 40,
        "edge",
        "binary with no known structure",
        "cad_reference by name only; never parsed",
    )
    folder = "cad_related/"
    add(
        folder + "bracket_v3.scdoc",
        b"SCDOC\0" + bytes(500),
        "normal",
        "model file whose siblings carry the same stem",
        "cad_reference; catalog.references lists bracket_v3.step, bracket_v3.pdf, bracket_v3.dwg and "
        "Bracket-V3.stl as same-name files (case and separators ignored), and other_plate.dxf and "
        "manifold_block.step as other drawings in the folder; S1 writes document_relations(REFERENCES)",
    )
    add(
        folder + "bracket_v3.step",
        step_text([("bracket", (0, 0, 0), (40, 25, 6))]),
        "normal",
        "STEP export of the bracket",
        "measured: 40 × 25 × 6 mm, volume 6000 mm³; related to bracket_v3.scdoc",
    )
    add(
        folder + "Bracket-V3.stl",
        stl_ascii(box_mesh(0, 0, 0, 40, 25, 6), "bracket"),
        "normal",
        "STL export with a different case and separator",
        "measured; counted as a same-stem sibling of bracket_v3",
    )
    add(
        folder + "bracket_v3.pdf",
        mini_pdf("Bracket V3 drawing, sheet 1"),
        "normal",
        "drawing",
        "goes to Route A1; related to the CAD files by stem",
        route="A1",
    )
    add(
        folder + "bracket_v3.dwg",
        b"AC1032" + bytes(600),
        "normal",
        "DWG sibling",
        "cad_reference; related to bracket_v3",
    )
    add(
        folder + "other_plate.dxf",
        DXF,
        "normal",
        "unrelated drawing in the same folder",
        "Route E; listed under 'other drawings in the folder', not as a same-name file",
        route="E",
    )
    add(
        folder + "manifold_block.step",
        step_text([("block", (0, 0, 0), (60, 40, 30))]),
        "normal",
        "unrelated STEP in the same folder",
        "measured on its own; listed as other CAD for the bracket files",
    )


def mismatch_cases() -> None:
    members = bundle()[:2]
    add(
        "mismatch/actual_pdf_named.zip",
        mini_pdf("not an archive"),
        "edge",
        "a PDF named .zip",
        "content wins (manual 1.1): Route A1, never G",
        route="A1",
    )
    add(
        "mismatch/actual_zip_named.pdf",
        zip_of(members),
        "edge",
        "a zip named .pdf",
        "content wins: Route G archive",
    )
    add(
        "mismatch/actual_zip_named.stl",
        zip_of(members),
        "edge",
        "a zip named .stl",
        "Route G: read as a zip (content wins) or PARSE_FAILURE HARD as an unreadable mesh; never a crash",
    )
    add(
        "mismatch/actual_stl_named.step",
        stl_ascii(box_mesh(0, 0, 0, 5, 5, 5), "cube5"),
        "edge",
        "an STL named .step",
        "Route G; measured as the STL it is, or PARSE_FAILURE HARD with the name kept",
    )
    add(
        "mismatch/actual_tar_named.zip",
        tar_of(members),
        "edge",
        "a tar named .zip",
        "read as tar (ustar magic)",
    )
    add(
        "mismatch/actual_gzip_named.zip",
        gz(CHANNELS.encode()),
        "edge",
        "a gzip named .zip",
        "read as gzip; payload goes to Route C",
    )
    docx = zip_of(
        [
            (
                "[Content_Types].xml",
                b'<?xml version="1.0"?><Types '
                b'xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default '
                b'Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" '
                b'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
            ),
            (
                "_rels/.rels",
                b'<?xml version="1.0"?><Relationships '
                b'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship '
                b'Id="rId1" '
                b'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',  # noqa: E501 (fixture content is one literal)
            ),
            (
                "word/document.xml",
                b'<?xml version="1.0"?><w:document '
                b'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p>'
                b"<w:r><w:t>Test report</w:t></w:r></w:p></w:body></w:document>",
            ),
        ]
    )
    add(
        "mismatch/negative_docx_is_a_zip.docx",
        docx,
        "negative",
        "an Office file is a zip inside",
        "never Route G (can_handle excludes .docx .xlsx .pptx .vsdx): Route A1",
        route="A1",
    )


# ---- manifest ----------------------------------------------------------------------------------------
STATIC = [
    (
        "corpus/real_scdoc_1.scdoc",
        "corpus",
        "normal",
        "G",
        "real SpaceClaim model (valve seal course material)",
        "cad_reference only; catalog holds name, size, folder, link; siblings from the same folder listed "
        "in references",
    ),
    (
        "corpus/real_wbpz_1.wbpz",
        "corpus",
        "normal",
        "G",
        "real ANSYS Workbench package, 12 MB, 23 entries (solver log, MatML, project, 57 MB result file)",
        "solver summary table, materials with units, systems in the catalog; large .rst result file not "
        "indexed as text",
    ),
    (
        "corpus/real_zip_latex_project.zip",
        "corpus",
        "normal",
        "G",
        "real zip: LaTeX project with a .synctex(busy) member",
        "members through the gate; LaTeX to A2; the busy-synctex member is skipped as junk",
    ),
    (
        "corpus/real_zip_wbpz_scdoc_mp4_pdf.zip",
        "corpus",
        "edge",
        "G",
        "real zip holding a wbpz, an scdoc, a 70 MB mp4 and a pdf: archive within archive plus a large "
        "media member",
        "wbpz expanded and indexed; mp4 goes to Route F; no member lost to the ratio guard",
    ),
    (
        "corpus/real_zip_pdf_pptx_xlsx_mp4.zip",
        "corpus",
        "edge",
        "G",
        "real 403 MB zip: 7 pdf, pptx, xlsx, one 363 MB mp4",
        "members dispatched by type; 363 MB member below the 1 GiB hold; memory stays under the cpu_parse "
        "limit",
    ),
    (
        "corpus/real_labjack_dat_1.dat.gz",
        "corpus",
        "normal",
        "G",
        "real LabJack run (9.8 MB .dat) gzipped locally; the three real .dat.gz are "
        "quarantined by the gate (_to_delete folder), so this is the only way to test the manual's step 4",
        "gunzip, then the .dat goes to Route C with the folder's channel map",
    ),
    (
        "web/zip/requests-2.32.3.zip",
        "web",
        "normal",
        "G",
        "compatibility only: real-world source tree zip with a top-level folder, docs, tests and images",
        "Route G; Python members to Route B, docs to A1/B; no junk flagged wrongly",
    ),
    (
        "web/tar/requests-2.32.3.tar.gz",
        "web",
        "normal",
        "G",
        "compatibility only: the same tree as a real .tar.gz",
        "same members as the zip",
    ),
    (
        "web/stl/Rocket.stl",
        "web",
        "normal",
        "G",
        "compatibility only: small rocket mesh (720 triangles), domain-adjacent",
        "measured; units not stated",
    ),
    (
        "web/stl/CubeSat_top.stl",
        "web",
        "normal",
        "G",
        "compatibility only: satellite part (4,696 triangles), domain-adjacent",
        "measured",
    ),
    ("web/stl/fan.stl", "web", "normal", "G", "compatibility only: ordinary mesh", "measured"),
    (
        "web/stl/torus_default_resolution.stl",
        "web",
        "normal",
        "G",
        "compatibility only: closed torus",
        "measured; watertight",
    ),
    (
        "web/step/face_recognition_sample_part.stp",
        "web",
        "normal",
        "G",
        "compatibility only: single part, 2 solids when tessellated",
        "measured by OpenCASCADE",
    ),
    (
        "web/step/red_cube_blue_cylinder.step",
        "web",
        "edge",
        "G",
        "compatibility only: two coloured solids",
        "solids = 2",
    ),
    (
        "web/step/as1_pe_203_assembly.stp",
        "web",
        "edge",
        "G",
        "compatibility only: AP203 assembly, 36 geometries",
        "measured as one scene; assembly parts counted",
    ),
    (
        "web/step/splinecage.stp",
        "web",
        "edge",
        "G",
        "compatibility only: spline surfaces",
        "measured; tessellation of NURBS works",
    ),
    (
        "web/step/Ventilator_heavy.stp",
        "web",
        "edge",
        "G",
        "compatibility only: 2.2 MB, about 129k triangles",
        "measured within the time limit",
    ),
    (
        "web/iges/surf114.igs",
        "web",
        "normal",
        "G",
        "compatibility only: IGES surfaces (CRLF line ends); cascadio reads it (142,464 triangles) but "
        "trimesh 5.1.1 has no IGES loader, found in sample preparation",
        "manual says IGES is measured: expected a measurement; if the route fails here, the defect is "
        "that cad.measure() calls trimesh.load(file_type='igs'); fix through "
        "cascadio.to_glb_bytes(file_type=IGES)",
    ),
    (
        "web/iges/curve_geom_plate.igs",
        "web",
        "edge",
        "G",
        "compatibility only: IGES with curves only and no surfaces (0 triangles)",
        "no measurable geometry: recorded with a note, not a crash (manual gap: not specified)",
    ),
    (
        "web/dwg/example_2000.dwg",
        "web",
        "normal",
        "G",
        "compatibility only: real AutoCAD 2000 drawing, 582 KB",
        "cad_reference only (manual: no open parser)",
    ),
]


def q(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def entry(c: dict, with_path: bool) -> str:
    keys = ["path", "origin", "kind", "route", "size_bytes", "sha256", "covers", "expect", "note"]
    lines = []
    for i, key in enumerate(k for k in keys if k in c and (with_path or k != "path")):
        value = c[key]
        text = q(value) if isinstance(value, str) else str(value)
        lines.append(("- " if i == 0 else "  ") + f"{key}: {text}")
    return "\n".join(lines)


def static_entries() -> list[dict]:
    found = []
    for rel, origin, kind, route, covers, expect in STATIC:
        path = SAMPLES / rel
        if not path.exists():
            continue
        data = path.read_bytes() if path.stat().st_size < 50_000_000 else None
        digest = (
            hashlib.sha256(data).hexdigest()
            if data is not None
            else hashlib.sha256(path.open("rb").read(1 << 20)).hexdigest() + "(first MiB)"
        )
        found.append(
            {
                "path": rel,
                "origin": origin,
                "kind": kind,
                "route": route,
                "size_bytes": path.stat().st_size,
                "sha256": digest,
                "covers": covers,
                "expect": expect,
            }
        )
    return found


def write_manifests() -> None:
    header = (
        "# Route G sample set. expect = what the manual (docs/architecture/03 §11) requires, written "
        "before running the route.\n"
        "# origin: synthetic (fictitious, byte-stable), corpus (real copies, never committed), web "
        "(compatibility only:\n"
        "# public files of no relevance to our domain, never ingested for real).\nversion: 1\nsamples:\n"
    )
    everything = static_entries() + CASES
    (SAMPLES / "MANIFEST.yaml").write_text(header + "\n".join(entry(c, True) for c in everything) + "\n")
    shareable = [c for c in static_entries() if c["origin"] == "web"] + CASES
    TEMPLATE.write_text(
        header.replace("corpus (real copies, never committed), ", "")
        + "\n".join(entry({**c, "path": c["path"]}, True) for c in shareable)
        + "\n"
    )


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    for build in (
        zip_cases,
        tar_cases,
        gz_cases,
        wbpz_cases,
        stl_cases,
        step_cases,
        iges_cases,
        reference_cases,
        mismatch_cases,
    ):
        build()
    write_manifests()
    kinds = {}
    for c in CASES:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    print(f"{len(CASES)} synthetic files in {OUT} {kinds}; manifest {SAMPLES / 'MANIFEST.yaml'}")


if __name__ == "__main__":
    main()
