"""Archive expansion with the bomb guard (file 03 §11 steps 1–4, edge cases).

Before and during extraction: compressed→uncompressed ratio ≤ 100 (per member and for the whole archive),
total uncompressed ≤ 5 GB, entries ≤ 50,000, nesting depth ≤ 3, no path traversal (``../``, absolute
paths, drive letters). Declared sizes are checked first and the actual bytes again while reading, so a
lying header cannot get past. A violation raises ``ArchiveBomb``; an encrypted member ``ArchiveEncrypted``.

Every leaf member goes through the gate (``backend/sync/gate.gate_item``) with ``parent_kind`` and the
archive's folder path plus the member's own folders, so junk inside archives (``.DS_Store``,
``site-packages``) is skipped by the same rules; ``kept_endings_by_parent_kind`` keeps ``.out`` inside
``.wbpz``. Members over 1 GB are held, not read. Nested archives (zip in zip, ``.tar.gz``) are expanded in
place, their members named ``outer/inner.zip!/member``. Symlinks are ignored.
"""

import gzip
import hashlib
import io
import tarfile
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from backend.postgres.enums import DriveItemStatus
from backend.sync.gate import GateConfig, GateInput, gate_item

MAX_RATIO = 100
MAX_TOTAL_BYTES = 5 * 1024**3
MAX_ENTRIES = 50_000
MAX_DEPTH = 3
MAX_MEMBER_BYTES = 1024**3
CHUNK = 1024 * 1024
NESTED_SUFFIXES = (".zip", ".tar", ".tgz", ".tar.gz", ".tar.bz2", ".tar.xz", ".gz")


class ArchiveBomb(ValueError):
    pass


class ArchiveEncrypted(ValueError):
    pass


@dataclass
class Member:
    path: str
    size: int
    status: str  # kept, skipped, held, symlink, archive
    reason: str = ""
    data: bytes | None = None
    sha256: str | None = None


@dataclass
class Budget:
    entries: int = 0
    total: int = 0
    members: list[Member] = field(default_factory=list)

    def entry(self) -> None:
        self.entries += 1
        if self.entries > MAX_ENTRIES:
            raise ArchiveBomb(f"more than {MAX_ENTRIES} entries")

    def grow(self, count: int, compressed_total: int) -> None:
        self.total += count
        if self.total > MAX_TOTAL_BYTES:
            raise ArchiveBomb(f"uncompressed total above {MAX_TOTAL_BYTES} bytes")
        if compressed_total and self.total > MAX_RATIO * compressed_total and self.total > CHUNK:
            raise ArchiveBomb(f"compression ratio above {MAX_RATIO}")


def archive_kind(name: str, head: bytes) -> str | None:
    folded = name.casefold()
    if folded.endswith(".wbpz"):
        return "wbpz"
    if folded.endswith((".tar.gz", ".tgz", ".tar", ".tar.bz2", ".tar.xz")):
        return "tar"
    if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06"):
        return "zip"
    if head.startswith(b"\x1f\x8b"):
        return "gzip"
    if len(head) > 262 and head[257:262] == b"ustar":
        return "tar"
    return None


def _safe_path(name: str) -> str:
    cleaned = name.replace("\\", "/")
    parts = PurePosixPath(cleaned).parts
    if cleaned.startswith("/") or ".." in parts or (parts and len(parts[0]) == 2 and parts[0][1] == ":"):
        raise ArchiveBomb(f"path traversal in member {name!r}")
    return "/".join(p for p in parts if p not in ("", "."))


def _read(stream, declared: int | None, compressed: int, budget: Budget, archive_compressed: int) -> bytes:
    out = bytearray()
    while chunk := stream.read(CHUNK):
        out += chunk
        budget.grow(len(chunk), archive_compressed)
        if declared is not None and len(out) > declared:
            raise ArchiveBomb("member larger than its declared size")
        if compressed and len(out) > MAX_RATIO * compressed and len(out) > CHUNK:
            raise ArchiveBomb(f"member compression ratio above {MAX_RATIO}")
    return bytes(out)


@dataclass
class Expander:
    gate: GateConfig
    folder_names: Sequence[str]
    archive_size: int
    budget: Budget = field(default_factory=Budget)

    def leaf(self, path: str, size: int, read, parent_kind: str, depth: int) -> None:
        name = PurePosixPath(path.split("!/")[-1]).name
        if name.casefold().endswith(NESTED_SUFFIXES) and not name.casefold().endswith(".synctex.gz"):
            if depth >= MAX_DEPTH:
                raise ArchiveBomb(f"nesting depth above {MAX_DEPTH} at {path}")
            data = read()
            kind = archive_kind(name, data[:512])
            if kind is not None:
                self.budget.members.append(Member(path, size, "archive", f"nested {kind}"))
                self.expand(data, name, kind, depth + 1, prefix=path + "!/")
                return
        if size > MAX_MEMBER_BYTES:
            self.budget.members.append(Member(path, size, "held", "member above 1 GB"))
            return
        folders = [*self.folder_names, *[p for p in path.replace("!/", "/").split("/")[:-1] if p]]
        verdict = gate_item(
            GateInput(name=name, size_bytes=size, folder_names=folders, parent_kind=parent_kind), self.gate
        )
        if verdict is not None:
            status = "held" if verdict.status == DriveItemStatus.HELD_LARGE_FILE else "skipped"
            self.budget.members.append(Member(path, size, status, verdict.gate_reason))
            return
        data = read()
        self.budget.members.append(
            Member(path, len(data), "kept", "", data, hashlib.sha256(data).hexdigest())
        )

    def expand(self, data: bytes, name: str, kind: str, depth: int = 1, prefix: str = "") -> list[Member]:
        if kind in ("zip", "wbpz"):
            self._zip(data, kind, depth, prefix)
        elif kind == "tar":
            self._tar(data, depth, prefix)
        elif kind == "gzip":
            self._gzip(data, name, depth, prefix)
        else:
            raise ArchiveBomb(f"unknown archive kind {kind}")
        return self.budget.members

    def _zip(self, data: bytes, kind: str, depth: int, prefix: str) -> None:
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise ArchiveBomb(f"not a readable ZIP: {exc}") from exc
        seen: dict[str, int] = {}
        with archive:
            for info in archive.infolist():
                self.budget.entry()
                if info.is_dir():
                    continue
                if info.flag_bits & 0x1:
                    raise ArchiveEncrypted(f"encrypted member {info.filename}")
                path = _safe_path(info.filename)
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    self.budget.members.append(
                        Member(prefix + path, info.file_size, "symlink", "symlink ignored")
                    )
                    continue
                if info.file_size > MAX_RATIO * max(info.compress_size, 1) and info.file_size > CHUNK:
                    raise ArchiveBomb(
                        f"member {info.filename} declares a compression ratio above {MAX_RATIO}"
                    )
                seen[path] = seen.get(path, 0) + 1
                full = prefix + path + (f"#{seen[path]}" if seen[path] > 1 else "")

                def read(info=info):
                    with archive.open(info) as stream:
                        return _read(
                            stream, info.file_size, info.compress_size, self.budget, self.archive_size
                        )

                self.leaf(full, info.file_size, read, kind, depth)

    def _tar(self, data: bytes, depth: int, prefix: str) -> None:
        try:
            archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
        except tarfile.TarError as exc:
            raise ArchiveBomb(f"not a readable tar: {exc}") from exc
        with archive:
            for info in archive:
                self.budget.entry()
                if info.isdir():
                    continue
                path = _safe_path(info.name)
                if info.issym() or info.islnk():
                    self.budget.members.append(Member(prefix + path, 0, "symlink", "symlink ignored"))
                    continue
                if not info.isfile():
                    continue

                def read(info=info):
                    stream = archive.extractfile(info)
                    return _read(stream, info.size, 0, self.budget, self.archive_size) if stream else b""

                self.leaf(prefix + path, info.size, read, "tar", depth)

    def _gzip(self, data: bytes, name: str, depth: int, prefix: str) -> None:
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as probe:
                probe.next()
            self._tar(data, depth, prefix)
            return
        except (tarfile.TarError, OSError, EOFError):
            pass
        member = name[:-3] if name.casefold().endswith(".gz") else f"{name}.out"
        self.budget.entry()
        try:
            content = _read(
                gzip.GzipFile(fileobj=io.BytesIO(data)), None, len(data), self.budget, self.archive_size
            )
        except (OSError, EOFError) as exc:
            raise ArchiveBomb(f"not a readable gzip stream: {exc}") from exc
        self.leaf(prefix + member, len(content), lambda: content, "gz", depth)
