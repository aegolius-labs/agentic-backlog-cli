from .base import BaseFileParser
from .markdown_parser import MarkdownAgentParser
from .python_parser import PYTHON_LANGUAGE, TreeSitterParser
from .visitors import TreeSitterVisitor


class ParserFactory:
    def __init__(self):
        self.parsers = {
            ".py": TreeSitterParser(PYTHON_LANGUAGE, TreeSitterVisitor),
            ".md": MarkdownAgentParser(),
        }

    def get_parser(self, ext: str) -> BaseFileParser | None:
        return self.parsers.get(ext)
