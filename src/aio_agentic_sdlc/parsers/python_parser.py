import hashlib
import os
from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Query, QueryCursor

from aio_agentic_sdlc.dag_models import EdgeType, NodeType
from aio_agentic_sdlc.source_locations import SourceLocation
from aio_agentic_sdlc.source_markers import canonical_node_marker

from .base import BaseFileParser

PYTHON_LANGUAGE = Language(tspython.language())
DEFINITION_TYPES = {
    "class_definition",
    "function_definition",
    "async_function_definition",
    "decorated_definition",
}


# aio-sdlc-mapping-approval: {"approved_at":"2026-08-13T19:29:14.286017-04:00","approved_by":"Felix","candidate_reality_id":"68d91d09-7a15-5e5c-8387-68ac2ec30139","evidence_digest":"a554f11c71a8625f074e1b0540fcd58bb7f1957fcde73b934e5103f21c90110a","intent_id":"9865715b-99a5-4dcb-ba92-90b03cc3cf1c","rationale":"Approved the TreeSitterParser source identity; parser responsibility, base type, and parse API match, without claiming behavioral verification.","schema_version":1,"source_path":"src/aio_agentic_sdlc/parsers/python_parser.py","source_sha256":"2b27f2d7d3f2908282a87bd7144a2a4160fdbf1fbf6a956c03815266a5eee949","symbol_kind":"class","symbol_name":"TreeSitterParser"}
# aio-sdlc-node: 9865715b-99a5-4dcb-ba92-90b03cc3cf1c
class TreeSitterParser(BaseFileParser):
    def __init__(self, language: Language, visitor_class: type):
        self.parser = Parser(language)
        self.visitor_class = visitor_class
        self.query = Query(language, "(comment) @comment")

    def parse(self, generator, file_path: str):
        try:
            raw_content = Path(file_path).read_bytes()
            content = raw_content.decode("utf-8")
        except UnicodeDecodeError:
            return

        tree = self.parser.parse(bytes(content, "utf8"))

        module_uuid = None
        cursor = QueryCursor(self.query)
        captures = cursor.captures(tree.root_node)

        for node in captures.get("comment", []):
            if node.parent is None or node.parent.type != "module":
                continue
            marker = canonical_node_marker(node.text.decode("utf8"))
            if marker is None:
                continue
            next_node = node.next_named_sibling
            marker_is_definition_adjacent = (
                next_node is not None
                and next_node.type in DEFINITION_TYPES
                and next_node.start_point.row == node.end_point.row + 1
            )
            if not marker_is_definition_adjacent:
                module_uuid = marker
                break

        module_id = (
            module_uuid if module_uuid else generator._resolve_module_id(file_path)
        )

        generator._add_node(
            id=module_id,
            node_type=NodeType.MODULE,
            name=os.path.basename(file_path),
            description=f"Module {module_id}",
            explicit_identity=module_uuid is not None,
            source_location=SourceLocation(
                path=generator._source_path(file_path),
                symbol_kind="module",
                symbol_name=os.path.basename(file_path),
                definition_line=1,
                marker_line=1,
                source_sha256=hashlib.sha256(raw_content).hexdigest(),
            ),
        )

        generator._add_edge("system_root", module_id, EdgeType.CONTAINS)

        visitor = self.visitor_class(
            generator,
            module_id,
            file_path=file_path,
            content=content,
            source_sha256=hashlib.sha256(raw_content).hexdigest(),
        )
        visitor.visit(tree.root_node)
