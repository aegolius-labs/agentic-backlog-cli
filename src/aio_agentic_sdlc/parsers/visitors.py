from typing import List

from tree_sitter import Node

from aio_agentic_sdlc.dag_models import EdgeType, NodeType


class TreeSitterVisitor:
    def __init__(self, generator, module_id: str):
        self.generator = generator
        self.module_id = module_id
        self.current_scope = module_id
        self.scope_stack = [module_id]

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
        else:
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
        class_id = f"{self.current_scope}.{name}"

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
            id=class_id, node_type=node_type, name=name, description=docstring
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

        func_id = f"{self.current_scope}.{name}"

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
            id=func_id, node_type=node_type, name=name, description=docstring
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
