import os

import yaml

from aio_agentic_sdlc.dag_models import EdgeType, NodeType

from .base import BaseFileParser


class MarkdownAgentParser(BaseFileParser):
    def parse(self, generator, file_path: str):
        rel_path = os.path.relpath(file_path, generator.root_dir)
        normalized_rel = rel_path.replace(os.sep, "/")
        if not normalized_rel.startswith(".agents/agents/"):
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            return

        if not content.startswith("---"):
            return

        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1]
            try:
                data = yaml.safe_load(frontmatter)
                if data and isinstance(data, dict):
                    name = data.get("name")
                    obj_type = data.get("type")
                    tools = data.get("tools")
                    desc = data.get("description", f"Agent {name}")

                    is_agent = False
                    if obj_type == "agent":
                        is_agent = True
                    elif obj_type is None and (name or tools is not None):
                        is_agent = True

                    if name and is_agent:
                        agent_id = name

                        # Extract Node ID from metadata (if present)
                        if "metadata" in data and isinstance(data["metadata"], dict):
                            node_id = data["metadata"].get("node_id")
                            if node_id:
                                agent_id = node_id

                        generator._add_node(
                            id=agent_id,
                            node_type=NodeType.AGENT,
                            name=name,
                            description=desc,
                        )
                        generator._add_edge("system_root", agent_id, EdgeType.CONTAINS)
            except yaml.YAMLError:
                pass
