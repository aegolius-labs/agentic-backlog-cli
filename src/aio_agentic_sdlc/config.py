import json
import os

from .workspace import CONFIG_FILE


def load_config(project_path="."):
    file_path = os.path.join(project_path, CONFIG_FILE)
    if not os.path.exists(file_path):
        return {}
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config_dict, project_path="."):
    file_path = os.path.join(project_path, CONFIG_FILE)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(config_dict, f, indent=2)
