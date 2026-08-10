"""Ephemeral source provenance for generated Reality nodes."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceLocation:
    path: str
    symbol_kind: str
    symbol_name: str
    definition_line: int
    marker_line: int
    source_sha256: str

    def as_dict(self) -> dict[str, str | int]:
        return {
            "path": self.path,
            "symbol_kind": self.symbol_kind,
            "symbol_name": self.symbol_name,
            "definition_line": self.definition_line,
            "marker_line": self.marker_line,
            "source_sha256": self.source_sha256,
        }
