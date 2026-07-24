import os


def extract_h2(filepath: str) -> list[str]:
    """
    Reads a markdown file and returns a list of strings containing all H2 headers (lines starting with '## ').
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    h2_headers = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("## "):
                h2_headers.append(line.rstrip("\n"))
    return h2_headers
