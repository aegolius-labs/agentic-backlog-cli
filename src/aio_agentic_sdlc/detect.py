import os
import re


def detect_frameworks(cwd="."):
    """Analyze the current working directory to detect the tech stack."""
    frameworks = []

    # Node.js / JavaScript
    if os.path.exists(os.path.join(cwd, "package.json")):
        frameworks.append("node")
        if os.path.exists(os.path.join(cwd, "yarn.lock")):
            frameworks.append("yarn")
        elif os.path.exists(os.path.join(cwd, "pnpm-lock.yaml")):
            frameworks.append("pnpm")
        else:
            frameworks.append("npm")

    # Python
    pyproject_path = os.path.join(cwd, "pyproject.toml")
    requirements_path = os.path.join(cwd, "requirements.txt")
    if os.path.exists(pyproject_path) or os.path.exists(requirements_path):
        frameworks.append("python")
        uses_uv = os.path.exists(os.path.join(cwd, "uv.lock"))
        if not uses_uv and os.path.exists(pyproject_path):
            with open(pyproject_path, encoding="utf-8") as pyproject_file:
                uses_uv = "uv" in pyproject_file.read()
        if uses_uv:
            frameworks.append("uv")

    # Rust
    if os.path.exists(os.path.join(cwd, "Cargo.toml")):
        frameworks.append("rust")

    return frameworks


def seed_from_openspec(cwd="."):
    """Parse tasks.md from Open-Spec into backlog items."""
    items = {}
    tasks_file = os.path.join(cwd, "tasks.md")
    if os.path.exists(tasks_file):
        with open(tasks_file, "r", encoding="utf-8") as f:
            for line in f:
                match = re.match(r"^\s*-\s*\[([ xX])\]\s+(.+)$", line)
                if match:
                    status_char = match.group(1).lower()
                    name = match.group(2).strip()
                    items[name] = {
                        "impact": 3,
                        "effort": 3,
                        "category": "Open-Spec Task",
                        "requires": [],
                        "ai_driven": False,
                        "status": "Completed" if status_char == "x" else "New",
                        "blockers": [],
                        "scores": {},
                    }
    return items


def seed_from_speckit(cwd="."):
    """Parse markdown files in specs/ from Spec-Kit into backlog items."""
    items = {}
    specs_dir = os.path.join(cwd, "specs")
    if os.path.exists(specs_dir) and os.path.isdir(specs_dir):
        for fname in os.listdir(specs_dir):
            if fname.endswith(".md"):
                fpath = os.path.join(specs_dir, fname)
                with open(fpath, "r", encoding="utf-8") as f:
                    for line in f:
                        match = re.match(r"^\s*-\s*\[([ xX])\]\s+(.+)$", line)
                        if match:
                            status_char = match.group(1).lower()
                            name = match.group(2).strip()
                            items[name] = {
                                "impact": 3,
                                "effort": 3,
                                "category": f"Spec-Kit Task ({fname})",
                                "requires": [],
                                "ai_driven": False,
                                "status": "Completed" if status_char == "x" else "New",
                                "blockers": [],
                                "scores": {},
                            }
    return items


def generate_seed_backlog(frameworks, cwd="."):
    """Generate a dictionary of seed items based on detected frameworks and specs."""
    items = {}

    # Try SDD framework parsing first
    openspec_items = seed_from_openspec(cwd)
    if openspec_items:
        items.update(openspec_items)

    speckit_items = seed_from_speckit(cwd)
    if speckit_items:
        items.update(speckit_items)

    # If SDD found tasks, do not add universal baselines to avoid clutter
    if items:
        return items

    # Universal baselines if no spec parsing succeeded
    items["Initial Project Documentation"] = {
        "impact": 5,
        "effort": 2,
        "category": "Documentation",
        "requires": [],
        "ai_driven": True,
        "status": "New",
        "blockers": [],
        "scores": {},
    }

    if "node" in frameworks:
        items["Configure ESLint/Prettier"] = {
            "impact": 4,
            "effort": 2,
            "category": "Code Quality",
            "requires": [],
            "ai_driven": True,
            "status": "New",
            "blockers": [],
            "scores": {},
        }
        items["Setup CI/CD Pipeline (Node)"] = {
            "impact": 5,
            "effort": 3,
            "category": "Infrastructure",
            "requires": ["Configure ESLint/Prettier"],
            "ai_driven": True,
            "status": "New",
            "blockers": [],
            "scores": {},
        }

    if "python" in frameworks:
        items["Configure Pytest infrastructure"] = {
            "impact": 4,
            "effort": 2,
            "category": "Testing",
            "requires": [],
            "ai_driven": True,
            "status": "New",
            "blockers": [],
            "scores": {},
        }
        items["Configure Linting (Ruff/Flake8)"] = {
            "impact": 4,
            "effort": 1,
            "category": "Code Quality",
            "requires": [],
            "ai_driven": True,
            "status": "New",
            "blockers": [],
            "scores": {},
        }

    if "rust" in frameworks:
        items["Configure Clippy and Rustfmt"] = {
            "impact": 4,
            "effort": 1,
            "category": "Code Quality",
            "requires": [],
            "ai_driven": True,
            "status": "New",
            "blockers": [],
            "scores": {},
        }

    return items
