import os
import re

import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Query, QueryCursor

from aio_agentic_sdlc.dag_models import EdgeType, NodeType

from .base import BaseFileParser

PYTHON_LANGUAGE = Language(tspython.language())
NODE_ID_PATTERN = re.compile(r"#\s*aio-sdlc-node:\s*([a-f0-9\-]+)", re.IGNORECASE)


class TreeSitterParser(BaseFileParser):
    def __init__(self, language: Language, visitor_class: type):
        self.parser = Parser(language)
        self.visitor_class = visitor_class
        self.query = Query(language, "(comment) @comment")

    def parse(self, generator, file_path: str):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            return

        tree = self.parser.parse(bytes(content, "utf8"))

        module_uuid = None
        cursor = QueryCursor(self.query)
        captures = cursor.captures(tree.root_node)

        for node in captures.get("comment", []):
            text = node.text.decode("utf8")
            match = NODE_ID_PATTERN.search(text)
            if match:
                module_uuid = match.group(1)
                break

        module_id = (
            module_uuid if module_uuid else generator._resolve_module_id(file_path)
        )

        generator._add_node(
            id=module_id,
            node_type=NodeType.MODULE,
            name=os.path.basename(file_path),
            description=f"Module {module_id}",
        )

        generator._add_edge("system_root", module_id, EdgeType.CONTAINS)

        visitor = self.visitor_class(generator, module_id)
        visitor.visit(tree.root_node)
