from .base import BaseFileParser
from .markdown_parser import MarkdownAgentParser
from .python_parser import PYTHON_LANGUAGE, TreeSitterParser
from .visitors import TreeSitterVisitor


# aio-sdlc-mapping-approval: {"approved_at":"2026-08-13T19:29:14.286017-04:00","approved_by":"Felix","candidate_reality_id":"a7278b66-0ac6-5e6b-91d7-0604d42cc40f","evidence_digest":"1c322789fdfb8510307391326e0f9c8b16eb36833922846aaaf460b2c857b854","intent_id":"d0307d83-371e-4bb6-925d-84a4b70beb6b","rationale":"Approved the ParserFactory source identity; extension-based parser selection responsibility and public API match.","schema_version":1,"source_path":"src/aio_agentic_sdlc/parsers/factory.py","source_sha256":"532714443f9a88c178c6e666de53447ca1c017f0525941802b4bdbe2ef088b03","symbol_kind":"class","symbol_name":"ParserFactory"}
# aio-sdlc-node: d0307d83-371e-4bb6-925d-84a4b70beb6b
class ParserFactory:
    def __init__(self):
        self.parsers = {
            ".py": TreeSitterParser(PYTHON_LANGUAGE, TreeSitterVisitor),
            ".md": MarkdownAgentParser(),
        }

    def get_parser(self, ext: str) -> BaseFileParser | None:
        return self.parsers.get(ext)
