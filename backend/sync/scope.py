"""Download and processing scopes (file 02 §3.1a): allowlists of root names, folder ids or path globs.

An empty scope means everything. A path glob is matched case-insensitively against the
computed path (``root/folder/…/name``); ``*`` also crosses ``/``, so ``APU/Test Plan 30/*``
covers the whole subtree. Nothing outside a scope is a flag: the item is only held.
"""

from collections.abc import Collection, Sequence
from fnmatch import fnmatchcase

from backend.postgres.enums import DriveItemStatus
from backend.sync.gate import Verdict

HELD_BY_DOWNLOAD_SCOPE = Verdict(DriveItemStatus.HELD_BY_SCOPE, "SCOPE:not_in_download_scope")


def in_scope(scope: Sequence[str], root_name: str, ancestor_folder_ids: Collection[str], path: str) -> bool:
    if not scope:
        return True
    folded_path = path.casefold()
    for entry in scope:
        if entry == root_name or entry in ancestor_folder_ids:
            return True
        if ("/" in entry or "*" in entry) and fnmatchcase(folded_path, entry.casefold()):
            return True
    return False
