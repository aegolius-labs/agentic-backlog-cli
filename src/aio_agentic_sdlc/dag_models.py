from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from aio_agentic_sdlc.intent_ir import IntentIR


class NodeType(str, Enum):
    SYSTEM = "system"
    CONTAINER = "container"
    MODULE = "module"
    COMPONENT = "component"
    ENDPOINT = "endpoint"
    ENTITY = "entity"
    AGENT = "agent"


class EdgeType(str, Enum):
    CONTAINS = "contains"
    DEPENDS_ON = "depends_on"
    CALLS = "calls"
    PUBLISHES = "publishes"
    SUBSCRIBES = "subscribes"
    READS = "reads"
    WRITES = "writes"
    IMPLEMENTS = "implements"


class Metadata(BaseModel):
    name: str
    version: str


class Node(BaseModel):
    id: str = Field(
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    )
    type: NodeType
    name: str
    domain: Optional[str] = None
    description: Optional[str] = None
    attributes: Optional[Dict[str, Any]] = None
    intent: Optional[IntentIR] = None


class Edge(BaseModel):
    source: str = Field(
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    )
    target: str = Field(
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    )
    type: EdgeType
    description: Optional[str] = None
