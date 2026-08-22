import os
from typing import Any, Dict, List

from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Edge, EdgeType, Metadata, NodeType
from aio_agentic_sdlc.dag_models import Node as DAGNode
from aio_agentic_sdlc.parsers.factory import ParserFactory
from aio_agentic_sdlc.source_locations import SourceLocation

IGNORED_DIRECTORIES = {
    ".aio-agentic-sdlc",
    ".aio-sdlc",  # Deprecated state directory; exclude during migration cleanup.
    ".git",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".qa-sandbox",
    ".ruff_cache",
    ".tox",
    ".uv-cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "node_modules",
}


def is_ignored_directory(directory: str) -> bool:
    """Return whether one directory name is outside deterministic Reality evidence."""

    normalized = directory.casefold()
    return normalized in IGNORED_DIRECTORIES or normalized.endswith(".egg-info")


_is_ignored_directory = is_ignored_directory


# aio-sdlc-mapping-approval: {"candidate_reality_id":"5f9d3dc7-cd7e-5402-86cd-356a4b6846fb","identity_approval":{"approved_at":"2026-08-13T19:29:14.286017-04:00","approved_by":"Felix","candidate_reality_id":"5f9d3dc7-cd7e-5402-86cd-356a4b6846fb","evidence_digest":"506a82e619bca8370b7af081f885edaa08bea033761e11a5b30924066e73b9f5","intent_id":"0fea8fea-9a23-404b-a16b-a9c9c3990e1b","rationale":"Approved the RealityDAGGenerator source identity; responsibility and public API match the reviewed Intention node.","schema_version":1,"source_path":"src/aio_agentic_sdlc/reality_dag_generator.py","source_sha256":"c688f5fe800d8178dae6bb861f71b8ac59e6015165e346bdecb647966371e242","symbol_kind":"class","symbol_name":"RealityDAGGenerator"},"intent_id":"0fea8fea-9a23-404b-a16b-a9c9c3990e1b","maintenance_approval":{"approved_at":"2026-08-21T23:03:05.512658-04:00","approved_by":"Felix","evidence_digest":"87063b8be5fd321aa8661dcffedbcdab8cc6ee06400a7a21cf769101d87961b3","rationale":"Felix approved refreshing the existing RealityDAGGenerator mapping receipt to bind current source after validated Reality ignore-boundary changes; identity remains unchanged and behavior remains separately evidenced.","supersedes_receipt_sha256":"db9054efbca14f4938ab695d3035cde3886bd24a637aa1c1a87f8fc37b4930c6"},"schema_version":2,"source_path":"src/aio_agentic_sdlc/reality_dag_generator.py","source_sha256":"9ed6dbbdcb45f593132102e887e897038c553d325b12cfa98cc9215f2c6de0ec","symbol_kind":"class","symbol_name":"RealityDAGGenerator"}
# aio-sdlc-node: 0fea8fea-9a23-404b-a16b-a9c9c3990e1b
class RealityDAGGenerator:
    """
    Generates a Reality DAG by statically analyzing source code.
    Implements a tree-sitter parser to be stack-agnostic.
    """

    def __init__(self, root_dir: str, system_name: str = "System"):
        self.root_dir = os.path.abspath(root_dir)
        self.system_name = system_name
        self.nodes: Dict[str, DAGNode] = {}
        self.edges: List[Edge] = []
        self.source_locations: Dict[str, List[SourceLocation]] = {}

        self.parser_factory = ParserFactory()

        # Add system node
        self._add_node(
            id="system_root",
            node_type=NodeType.SYSTEM,
            name=self.system_name,
            description="Root project system",
        )

    def _id_to_uuid(self, id_str: str) -> str:
        import uuid

        id_str = str(id_str)
        try:
            uuid.UUID(id_str)
            return id_str
        except ValueError:
            return str(uuid.uuid5(uuid.NAMESPACE_DNS, id_str))

    def _add_node(
        self,
        id: str,
        node_type: NodeType,
        name: str,
        domain: str = None,
        description: str = None,
        attributes: Dict[str, Any] = None,
        source_location: SourceLocation = None,
        explicit_identity: bool = False,
    ):
        uid = self._id_to_uuid(id)
        if explicit_identity and uid in self.nodes:
            existing_locations = self.source_locations.get(uid, [])
            if source_location not in existing_locations:
                existing = (
                    ", ".join(
                        f"{location.path}:{location.marker_line}"
                        for location in existing_locations
                    )
                    or f"existing {self.nodes[uid].type.value} node"
                )
                current = (
                    f"{source_location.path}:{source_location.marker_line}"
                    if source_location is not None
                    else "unknown source"
                )
                raise ValueError(
                    f"canonical source marker collides with existing identity {uid}: "
                    f"{existing} and {current}"
                )
        if uid not in self.nodes:
            self.nodes[uid] = DAGNode(
                id=uid,
                type=node_type,
                name=name,
                domain=domain,
                description=description,
                attributes=attributes,
            )
        if source_location is not None:
            locations = self.source_locations.setdefault(uid, [])
            if source_location not in locations:
                locations.append(source_location)
                locations.sort(
                    key=lambda location: (
                        location.path,
                        location.marker_line,
                        location.symbol_kind,
                    )
                )
        return uid

    def _add_edge(
        self, source: str, target: str, edge_type: EdgeType, description: str = None
    ):
        u_source = self._id_to_uuid(source)
        u_target = self._id_to_uuid(target)
        for edge in self.edges:
            if (
                edge.source == u_source
                and edge.target == u_target
                and edge.type == edge_type
            ):
                return
        self.edges.append(
            Edge(
                source=u_source,
                target=u_target,
                type=edge_type,
                description=description,
            )
        )

    def _resolve_module_id(self, file_path: str) -> str:
        rel_path = os.path.relpath(file_path, self.root_dir)
        module_path, _ = os.path.splitext(rel_path)
        return module_path.replace(os.sep, ".")

    def _source_path(self, file_path: str) -> str:
        return os.path.relpath(file_path, self.root_dir).replace(os.sep, "/")

    def generate(self) -> DAGManager:
        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = sorted(
                directory for directory in dirs if not is_ignored_directory(directory)
            )

            for file in sorted(files):
                _, ext = os.path.splitext(file)
                parser = self.parser_factory.get_parser(ext)
                if parser:
                    file_path = os.path.join(root, file)
                    parser.parse(self, file_path)

        valid_edges = []
        for edge in self.edges:
            if edge.type == EdgeType.DEPENDS_ON:
                if edge.target in self.nodes:
                    valid_edges.append(edge)
            else:
                valid_edges.append(edge)

        self.edges = valid_edges

        metadata = Metadata(name=self.system_name, version="1.0.0")
        return DAGManager(
            metadata=metadata, nodes=list(self.nodes.values()), edges=self.edges
        )
