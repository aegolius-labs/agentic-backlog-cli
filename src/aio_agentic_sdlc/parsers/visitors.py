from typing import List

from tree_sitter import Node

from aio_agentic_sdlc.dag_models import EdgeType, NodeType
from aio_agentic_sdlc.source_locations import SourceLocation
from aio_agentic_sdlc.source_markers import canonical_node_marker

STRUCTURAL_CONTAINER_TYPES = {
    "module",
    "block",
    "if_statement",
    "elif_clause",
    "else_clause",
    "try_statement",
    "except_clause",
    "finally_clause",
    "with_statement",
    "for_statement",
    "while_statement",
    "match_statement",
    "case_clause",
}


class TreeSitterVisitor:
    def __init__(
        self,
        generator,
        module_id: str,
        *,
        file_path: str,
        content: str,
        source_sha256: str,
    ):
        self.generator = generator
        self.module_id = module_id
        self.current_scope = module_id
        self.scope_stack = [module_id]
        self.file_path = file_path
        self.lines = content.splitlines()
        self.source_sha256 = source_sha256

    def _definition_identity(self, node: Node, decorators: List[Node]):
        marker_row = min(
            [
                node.start_point.row,
                *(decorator.start_point.row for decorator in decorators),
            ]
        )
        marker = None
        if marker_row > 0:
            marker = canonical_node_marker(self.lines[marker_row - 1])
        marker_line = marker_row if marker is not None else marker_row + 1
        return marker, marker_line

    def _source_location(
        self,
        *,
        node: Node,
        decorators: List[Node],
        symbol_kind: str,
        symbol_name: str,
    ) -> SourceLocation:
        _, marker_line = self._definition_identity(node, decorators)
        return SourceLocation(
            path=self.generator._source_path(self.file_path),
            symbol_kind=symbol_kind,
            symbol_name=symbol_name,
            definition_line=node.start_point.row + 1,
            marker_line=marker_line,
            source_sha256=self.source_sha256,
        )

    def visit(self, node: Node):
        if node.type == "class_definition":
            self.visit_class_definition(node, [])
        elif node.type in ("function_definition", "async_function_definition"):
            self.visit_function_definition(node, [])
        elif node.type == "decorated_definition":
            self.visit_decorated_definition(node)
        elif node.type == "import_statement":
            self.visit_import_statement(node)
        elif node.type == "import_from_statement":
            self.visit_import_from_statement(node)
        elif node.type in STRUCTURAL_CONTAINER_TYPES:
            for child in node.children:
                if child.is_named:
                    self.visit(child)

    def visit_decorated_definition(self, node: Node):
        decorators = []
        for child in node.children:
            if child.type == "decorator":
                decorators.append(child)

        for child in node.children:
            if child.type == "class_definition":
                self.visit_class_definition(child, decorators)
            elif child.type in ("function_definition", "async_function_definition"):
                self.visit_function_definition(child, decorators)

    def visit_class_definition(self, node: Node, decorators: List[Node]):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf8")
        marker, _ = self._definition_identity(node, decorators)
        class_id = marker or f"{self.current_scope}.{name}"

        is_entity = False
        superclasses_node = node.child_by_field_name("superclasses")
        if superclasses_node:
            for child in superclasses_node.children:
                if child.type == "identifier":
                    base_name = child.text.decode("utf8")
                    if base_name in ["BaseModel", "Model", "Entity"]:
                        is_entity = True

        node_type = NodeType.ENTITY if is_entity else NodeType.COMPONENT

        docstring = f"Class {name}"
        body = node.child_by_field_name("body")
        if body and len(body.children) > 0:
            first_stmt = body.children[0]
            if first_stmt.type == "expression_statement":
                first_expr = first_stmt.children[0]
                if first_expr.type == "string":
                    docstring = first_expr.text.decode("utf8").strip("'\"")

        self.generator._add_node(
            id=class_id,
            node_type=node_type,
            name=name,
            description=docstring,
            explicit_identity=marker is not None,
            source_location=self._source_location(
                node=node,
                decorators=decorators,
                symbol_kind="class",
                symbol_name=name,
            ),
        )
        self.generator._add_edge(self.current_scope, class_id, EdgeType.CONTAINS)

        self.scope_stack.append(class_id)
        self.current_scope = class_id

        if body:
            for child in body.children:
                if child.is_named:
                    self.visit(child)

        self.scope_stack.pop()
        self.current_scope = self.scope_stack[-1]

    def _extract_decorator_names(self, decorators: List[Node]) -> List[str]:
        names = []
        for dec in decorators:
            for child in dec.children:
                if child.type == "identifier":
                    names.append(child.text.decode("utf8"))
                elif child.type == "attribute":
                    attr_name = child.child_by_field_name("attribute")
                    if attr_name:
                        names.append(attr_name.text.decode("utf8"))
                elif child.type == "call":
                    func = child.child_by_field_name("function")
                    if func:
                        if func.type == "identifier":
                            names.append(func.text.decode("utf8"))
                        elif func.type == "attribute":
                            attr_name = func.child_by_field_name("attribute")
                            if attr_name:
                                names.append(attr_name.text.decode("utf8"))
        return names

    def visit_function_definition(self, node: Node, decorators: List[Node]):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        name = name_node.text.decode("utf8")
        if name.startswith("_") and name != "__init__":
            return

        marker, _ = self._definition_identity(node, decorators)
        func_id = marker or f"{self.current_scope}.{name}"

        is_endpoint = False
        dec_names = self._extract_decorator_names(decorators)
        for d in dec_names:
            if d in ["get", "post", "put", "delete", "patch", "route", "endpoint"]:
                is_endpoint = True

        node_type = NodeType.ENDPOINT if is_endpoint else NodeType.COMPONENT

        docstring = f"Function {name}"
        body = node.child_by_field_name("body")
        if body and len(body.children) > 0:
            first_stmt = body.children[0]
            if first_stmt.type == "expression_statement":
                first_expr = first_stmt.children[0]
                if first_expr.type == "string":
                    docstring = first_expr.text.decode("utf8").strip("'\"")

        self.generator._add_node(
            id=func_id,
            node_type=node_type,
            name=name,
            description=docstring,
            explicit_identity=marker is not None,
            source_location=self._source_location(
                node=node,
                decorators=decorators,
                symbol_kind="function",
                symbol_name=name,
            ),
        )
        self.generator._add_edge(self.current_scope, func_id, EdgeType.CONTAINS)

    def visit_import_statement(self, node: Node):
        for child in node.children:
            if child.type == "dotted_name":
                imported_module = child.text.decode("utf8")
                self.generator._add_edge(
                    self.module_id, imported_module, EdgeType.DEPENDS_ON
                )
            elif child.type == "aliased_import":
                for subchild in child.children:
                    if subchild.type == "dotted_name":
                        imported_module = subchild.text.decode("utf8")
                        self.generator._add_edge(
                            self.module_id, imported_module, EdgeType.DEPENDS_ON
                        )
                        break

    def visit_import_from_statement(self, node: Node):
        module_name_node = node.child_by_field_name("module_name")
        if module_name_node:
            imported_module = module_name_node.text.decode("utf8")
            self.generator._add_edge(
                self.module_id, imported_module, EdgeType.DEPENDS_ON
            )
        else:
            for child in node.children:
                if child.type == "dotted_name":
                    imported_module = child.text.decode("utf8")
                    self.generator._add_edge(
                        self.module_id, imported_module, EdgeType.DEPENDS_ON
                    )
                    break
