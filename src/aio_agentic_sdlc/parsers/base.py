from typing import Any


class BaseFileParser:
    def parse(self, generator: Any, file_path: str):
        raise NotImplementedError
