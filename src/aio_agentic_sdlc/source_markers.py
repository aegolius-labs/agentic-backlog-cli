"""Canonical source-marker parsing shared by Reality and mapping workflows."""

from __future__ import annotations

import re
from uuid import UUID

NODE_MARKER_PREFIX = "aio-sdlc-node:"
MAPPING_APPROVAL_PREFIX = "aio-sdlc-mapping-approval:"
NODE_MARKER_PATTERN = re.compile(
    r"^[ \t]*#\s*aio-sdlc-node:\s*([a-fA-F0-9-]+)\s*$",
    re.MULTILINE,
)


def canonical_node_marker(line: str) -> str | None:
    """Return a canonical UUID only when the entire comment is a valid marker."""

    match = NODE_MARKER_PATTERN.fullmatch(line.rstrip("\r\n"))
    if not match:
        return None
    try:
        return str(UUID(match.group(1)))
    except ValueError:
        return None


def iter_canonical_node_markers(content: str):
    """Yield canonical UUIDs from valid Python source-marker comment lines."""

    for match in NODE_MARKER_PATTERN.finditer(content):
        try:
            yield str(UUID(match.group(1)))
        except ValueError:
            continue
