#!/usr/bin/env python3
import argparse
import importlib.resources
import json
import os
import sys

from .config import save_config
from .core import (
    VALID_STATUSES,
    _get_blockers,
    _get_status,
    add_blocker,
    add_item,
    get_next_item,
    get_requires,
    load_backlog,
    prioritize_items,
    remove_blocker,
    remove_item,
    save_backlog,
    set_status,
    update_item,
)

BACKLOG_FILE = "backlog.json"

STATUS_BADGES = {
    "New": "🆕",
    "In Progress": "🚧",
    "Completed": "✅",
    "Blocked": "🚫",
}


def _inject_agent_skills():
    """Extract SKILL.md from package and inject into the workspace."""
    try:
        content = (
            importlib.resources.files("aio_agentic_sdlc")
            .joinpath("templates", "aio-agentic-sdlc", "SKILL.md")
            .read_text(encoding="utf-8")
        )
    except Exception as e:
        print(
            f"[WARNING] Could not load bundled SKILL.md template: {e}", file=sys.stderr
        )
        return

    skill_dir = os.path.join(".agent", "skills", "aio-agentic-sdlc")
    os.makedirs(skill_dir, exist_ok=True)

    skill_file = os.path.join(skill_dir, "SKILL.md")
    with open(skill_file, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Success! Injected agent skill into {skill_file}")


def _inject_platform_rules(platforms_str):
    """Generate platform-specific configuration files based on the SSoT rules."""
    if not platforms_str:
        return

    try:
        rules_content = (
            importlib.resources.files("aio_agentic_sdlc")
            .joinpath("templates", "aio-agentic-sdlc", "RULES.md")
            .read_text(encoding="utf-8")
        )
    except Exception as e:
        print(
            f"[WARNING] Could not load bundled RULES.md template: {e}", file=sys.stderr
        )
        return

    platforms = [p.strip().lower() for p in platforms_str.split(",")]

    for platform in platforms:
        if platform == "claude":
            with open("CLAUDE.md", "a", encoding="utf-8") as f:
                f.write(f"\n## Agentic Backlog Rules\n{rules_content}\n")
            print("Success! Injected rules into CLAUDE.md")

        elif platform == "cursor":
            cursor_dir = os.path.join(".cursor", "rules")
            os.makedirs(cursor_dir, exist_ok=True)
            cursor_file = os.path.join(cursor_dir, "aio-agentic-sdlc.mdc")
            with open(cursor_file, "w", encoding="utf-8") as f:
                f.write(
                    f"---\ndescription: Agentic Backlog Behavioral Rules\nglobs: *\n---\n\n{rules_content}"
                )
            print(f"Success! Injected rules into {cursor_file}")

        elif platform in ("copilot", "vscode", "gh-copilot"):
            gh_dir = ".github"
            os.makedirs(gh_dir, exist_ok=True)
            copilot_file = os.path.join(gh_dir, "copilot-instructions.md")
            with open(copilot_file, "a", encoding="utf-8") as f:
                f.write(f"\n## Agentic Backlog Rules\n{rules_content}\n")
            print(f"Success! Injected rules into {copilot_file}")

        elif platform == "antigravity":
            agy_dir = os.path.join(".agents", "rules")
            os.makedirs(agy_dir, exist_ok=True)
            agy_file = os.path.join(agy_dir, "aio-agentic-sdlc.md")
            with open(agy_file, "w", encoding="utf-8") as f:
                f.write(rules_content)
            print(f"Success! Injected rules into {agy_file}")

        elif platform == "agile":
            with open("AGENTS.md", "a", encoding="utf-8") as f:
                f.write(f"\n## Agentic Backlog Rules\n{rules_content}\n")
            print("Success! Injected rules into AGENTS.md")

        else:
            print(
                f"[WARNING] Unknown platform '{platform}'. Supported: claude, cursor, copilot, antigravity, agile",
                file=sys.stderr,
            )


def init_cmd(args):
    print("\n--- Agentic-Backlog Initialization ---")
    print("1. Simple Hierarchy: Epic -> Feature -> Task/Bug")
    print(
        "2. Deep Hierarchy: Initiative -> Theme -> Epic -> Feature -> User Story/Tech Story/Bug -> Task -> SubTask"
    )
    print("3. Custom Hierarchy: Define your own")
    try:
        choice = (
            input("Select your Semantic Roadmap Graph schema (1/2/3) [1]: ").strip()
            or "1"
        )
    except (EOFError, OSError, IOError):
        choice = "1"

    hierarchy = {}
    if choice == "1":
        hierarchy = {"1": ["Epic"], "2": ["Feature"], "3": ["Task", "Bug"]}
    elif choice == "2":
        hierarchy = {
            "1": ["Initiative"],
            "2": ["Theme"],
            "3": ["Epic"],
            "4": ["Feature"],
            "5": ["User Story", "Tech Story", "Bug"],
            "6": ["Task"],
            "7": ["SubTask"],
        }
    else:
        print(
            "Define your custom hierarchy levels (comma separated types). Press Enter with no input to finish."
        )
        level = 1
        while True:
            try:
                types_input = input(f"Level {level} types: ").strip()
            except (EOFError, OSError, IOError):
                break
            if not types_input:
                break
            hierarchy[str(level)] = [t.strip() for t in types_input.split(",")]
            level += 1

    try:
        val_choice = (
            input(
                "Select Validation Mode: 1. Strict (direct parent only), 2. Flex (any higher level parent) [2]: "
            ).strip()
            or "2"
        )
    except (EOFError, OSError, IOError):
        val_choice = "2"
    validation_mode = "strict" if val_choice == "1" else "flex"

    config = {
        "core": {"validation_mode": validation_mode, "mode": "local"},
        "hierarchy": hierarchy,
    }

    save_config(config)
    from .core import BACKLOG_FILE

    if not os.path.exists(BACKLOG_FILE):
        nodes = {}
        if not getattr(args, "empty", False):
            try:
                from .detect import detect_frameworks, generate_seed_backlog

                frameworks = detect_frameworks()
                if frameworks:
                    print(
                        f"[Info] Detected frameworks: {', '.join(frameworks)}",
                        file=sys.stderr,
                    )
                items = generate_seed_backlog(frameworks)
                for name, i in items.items():
                    nodes[name] = i
                    nodes[name]["item_type"] = "Task"
            except ImportError:
                pass

        data = {"nodes": nodes, "edges": []}
        save_backlog(data, operation="backlog.initialize")

        if nodes:
            print(f"Success! Initialized {BACKLOG_FILE} with {len(nodes)} seed items.")
        else:
            print(f"Success! Initialized empty {BACKLOG_FILE}")
    else:
        print(f"File {BACKLOG_FILE} already exists. Schema updated.")

    _inject_agent_skills()
    platforms_arg = getattr(args, "platforms", None)
    if platforms_arg:
        _inject_platform_rules(platforms_arg)


def add_cmd(args):
    warnings = add_item(
        name=args.name,
        impact=args.impact,
        effort=args.effort,
        category=args.category,
        description=getattr(args, "description", None),
        requires=getattr(args, "requires", None),
        ai_driven=args.ai_driven,
        status=args.status,
        blockers=args.blockers,
    )
    for w in warnings:
        print(f"[WARNING] {w}", file=sys.stderr)
    print(f"Success! Added '{args.name}' to backlog.")


def update_cmd(args):
    try:
        warnings = update_item(
            name=args.name,
            impact=args.impact,
            effort=args.effort,
            category=getattr(args, "category", None),
            description=getattr(args, "description", None),
            requires=getattr(args, "requires", None),
            ai_driven=args.ai_driven,
            status=args.status,
            blockers=args.blockers,
        )
        for w in warnings:
            print(f"[WARNING] {w}", file=sys.stderr)
        print(f"Success! Updated '{args.name}'.")
    except ValueError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


def prioritize_cmd(args):
    try:
        if prioritize_items():
            print("Success! Backlog prioritized.")
        else:
            print("Backlog is empty.")
    except ValueError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


def export_cmd(args):
    data = load_backlog()
    nodes = data.get("nodes", {})

    out_file = args.out
    lines = [
        "# Prioritized Backlog",
        "",
        "This backlog is automatically managed. Scores are calculated using a 3D Matrix (Impact/Effort/Dependency).",
        "Topological sorting guarantees prerequisites are fulfilled first.",
        "",
    ]

    for i, (name, item) in enumerate(nodes.items(), 1):
        ai_tag = " 🤖 *(AI Generated Skeleton)*" if item.get("ai_driven") else ""
        reqs = ", ".join(get_requires(data, name)) or "None"
        scores = item.get("scores", {})
        base = scores.get("base", 0)
        final = scores.get("final", 0)
        status = _get_status(item)
        badge = STATUS_BADGES.get(status, "")

        lines.append(f"## {i}. {badge} {name}{ai_tag}")
        lines.append(f"**Status:** {status}")
        lines.append(f"**Category:** {item.get('category', 'None')}")
        lines.append(f"**Dependencies:** {reqs}")
        lines.append(
            f"**Matrix:** Impact {item.get('impact', 0)} / Effort {item.get('effort', 0)} (Base: {base}) -> **Final Score: {final}**"
        )
        desc = item.get("description")
        if desc:
            lines.append("")
            lines.append(f"**Description:**\n{desc}")
        blockers = _get_blockers(item)
        if blockers:
            lines.append("")
            lines.append(f"> **⚠️ Blocked by:** {', '.join(blockers)}")
        lines.append("")

    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Success! Exported human-readable backlog to {out_file}")


def status_cmd(args):
    try:
        set_status(args.name, args.new_status)
        print(f"Success! '{args.name}' status set to '{args.new_status}'.")
    except ValueError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


def block_cmd(args):
    try:
        add_blocker(args.name, args.reason)
        print(f"Success! Added blocker to '{args.name}': {args.reason}")
    except ValueError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


def unblock_cmd(args):
    try:
        remove_blocker(args.name, args.reason)
        print(f"Success! Removed blocker from '{args.name}': {args.reason}")
    except ValueError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


def remove_cmd(args):
    try:
        remove_item(args.name)
        print(f"Success! Removed '{args.name}' completely from backlog.")
    except ValueError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


def next_cmd(args):
    target_data, warning = get_next_item()

    if target_data is None:
        result = {"target": None, "warning": warning}
        if args.format == "human":
            print(warning)
        else:
            print(json.dumps(result, indent=2))
        return

    result = {"target": target_data}
    if warning:
        result["warning"] = warning

    if args.format == "human":
        print(f"Next workable item: {target_data['name']}")
        if target_data.get("description"):
            print(f"  Description: {target_data['description']}")
        print(f"  Impact: {target_data['impact']} | Effort: {target_data['effort']}")
        print(f"  Category: {target_data['category']}")
        print(f"  Score: {target_data['scores'].get('final', 'N/A')}")
        if warning:
            print(f"  [!] {warning}")
    else:
        print(json.dumps(result, indent=2))


async def _run_architect_subagent(inbox_files):
    import os

    from google.antigravity import Agent, CapabilitiesConfig, LocalAgentConfig

    prompt_path = os.path.join(
        ".agents", "agents", "sdlc_architect", "system_prompt.md"
    )
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            system_instructions = f.read()
    except FileNotFoundError:
        system_instructions = "You are the Technical Architect."

    config = LocalAgentConfig(
        system_instructions=system_instructions, capabilities=CapabilitiesConfig()
    )

    files_str = ", ".join(inbox_files)
    prompt = f"Process the following PRDs from the inbox/ directory: {files_str}. Map them to intention-dag.yaml."
    async with Agent(config) as agent:
        await agent.chat(prompt)


def plan_cmd(args):
    import asyncio
    import glob
    import json
    import os

    from .archiver import PRDArchiver
    from .dag_manager import DAGManager
    from .diffing_engine import DiffingEngine

    try:
        if os.path.exists("inbox") and os.path.isdir("inbox"):
            inbox_files = glob.glob(os.path.join("inbox", "*.md"))
            if inbox_files:
                asyncio.run(_run_architect_subagent(inbox_files))
                archiver = PRDArchiver()

                # Check if PRDs were reflected in intention-dag.yaml
                dag_nodes = set()
                try:
                    import yaml

                    with open("intention-dag.yaml", "r", encoding="utf-8") as f:
                        content = f.read()
                        dag_data = yaml.safe_load(content) or {}
                    nodes = dag_data.get("nodes", [])
                    if isinstance(nodes, list):
                        for n in nodes:
                            if isinstance(n, dict):
                                if "id" in n:
                                    dag_nodes.add(n["id"])
                                if "name" in n:
                                    dag_nodes.add(n["name"])
                            else:
                                dag_nodes.add(str(n))
                    elif isinstance(nodes, dict):
                        dag_nodes.update(nodes.keys())
                except Exception:
                    pass

                for file_path in inbox_files:
                    try:
                        filename = os.path.basename(file_path)
                        if filename in dag_nodes:
                            archiver.archive(file_path)
                        else:
                            print(
                                f"Warning: PRD {filename} was not reflected in intention-dag.yaml. Skipping archive.",
                                file=sys.stderr,
                            )
                    except Exception as e:
                        print(f"Error archiving {file_path}: {e}", file=sys.stderr)

        intention_dag = DAGManager.load("intention-dag.yaml")
        reality_dag = DAGManager.load("reality-dag.yaml")
        engine = DiffingEngine(intention_dag, reality_dag)
        diff = engine.calculate_diff()
        print(json.dumps(diff, indent=2))
    except Exception as e:
        print(f"Error computing diff: {e}", file=sys.stderr)
        sys.exit(1)


def apply_cmd(args):
    import asyncio

    from .orchestrator_loop import main_loop

    try:
        asyncio.run(main_loop())
        print("Apply completed.")
    except Exception as e:
        print(f"Error during apply: {e}", file=sys.stderr)
        sys.exit(1)


def migrate_state_cmd(args):
    from .state import migrate_backlog, retire_legacy_backlog

    result = migrate_backlog(".")
    if args.retire_legacy:
        result["legacy"] = retire_legacy_backlog(".")
    print(json.dumps(result, indent=2))


def migrate_ids_cmd(args):
    import os
    import uuid

    import yaml

    id_map = {}

    def migrate_file(filepath):
        if not os.path.exists(filepath):
            return
        print(f"Migrating {filepath}...")
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        nodes = data.get("nodes", [])
        edges = data.get("edges", [])

        migrated_count = 0
        for node in nodes:
            old_id = str(node.get("id", ""))
            try:
                # check if already a valid UUID
                uuid.UUID(old_id)
            except ValueError:
                # generate a new UUID
                if old_id not in id_map:
                    id_map[old_id] = str(uuid.uuid4())
                node["id"] = id_map[old_id]
                migrated_count += 1

        for edge in edges:
            old_source = str(edge.get("source", ""))
            old_target = str(edge.get("target", ""))
            if old_source in id_map:
                edge["source"] = id_map[old_source]
            if old_target in id_map:
                edge["target"] = id_map[old_target]

        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(data, f, sort_keys=False, default_flow_style=False)
        print(f"Migrated {migrated_count} node IDs in {filepath}.")

    migrate_file("intention-dag.yaml")
    migrate_file("reality-dag.yaml")
    print("Migration complete.")


def main():
    parser = argparse.ArgumentParser(description="Deterministic backlog manager.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_init = subparsers.add_parser(
        "init", help="Initialize the local backlog and configuration"
    )
    p_init.add_argument(
        "--empty",
        action="store_true",
        help="Skip auto-detecting frameworks for seed items",
    )
    p_init.add_argument(
        "--platforms",
        help="Comma-separated platforms to generate rules for (claude, cursor, copilot, antigravity, agile)",
    )

    p_add = subparsers.add_parser("add", help="Add an item")
    p_add.add_argument("name")
    p_add.add_argument("--impact", type=int, choices=range(1, 6), required=True)
    p_add.add_argument("--effort", type=int, choices=range(1, 6), required=True)
    p_add.add_argument("--category", required=True)
    p_add.add_argument(
        "--description", required=True, help="Detailed description of the task"
    )
    p_add.add_argument("--requires", help="Comma-separated dependencies")
    p_add.add_argument("--ai-driven", action="store_true")
    p_add.add_argument(
        "--status",
        default="New",
        choices=VALID_STATUSES,
        help="Initial status (default: New)",
    )
    p_add.add_argument("--blockers", help="Comma-separated blockers")

    p_update = subparsers.add_parser("update", help="Update an item")
    p_update.add_argument("name")
    p_update.add_argument("--impact", type=int, choices=range(1, 6))
    p_update.add_argument("--effort", type=int, choices=range(1, 6))
    p_update.add_argument("--category")
    p_update.add_argument("--description", help="Detailed description of the task")
    p_update.add_argument("--requires")
    p_update.add_argument("--ai-driven", action="store_true")
    p_update.add_argument("--status", choices=VALID_STATUSES)
    p_update.add_argument(
        "--blockers", help="Comma-separated blockers (replaces existing)"
    )

    p_status = subparsers.add_parser("status", help="Set item status")
    p_status.add_argument("name")
    p_status.add_argument(
        "new_status",
        choices=VALID_STATUSES,
        metavar="STATUS",
        help=f"One of: {', '.join(VALID_STATUSES)}",
    )

    p_block = subparsers.add_parser("block", help="Add a blocker to an item")
    p_block.add_argument("name")
    p_block.add_argument("reason", help="Blocker description")

    p_unblock = subparsers.add_parser("unblock", help="Remove a blocker from an item")
    p_unblock.add_argument("name")
    p_unblock.add_argument("reason", help="Blocker description to remove")

    p_remove = subparsers.add_parser("remove", help="Remove an item completely")
    p_remove.add_argument("name")

    subparsers.add_parser("prioritize", help="Prioritize and sort")

    p_next = subparsers.add_parser("next", help="Get next workable item")
    p_next.add_argument(
        "--format",
        choices=["json", "human"],
        default="json",
        help="Output format (default: json)",
    )

    p_export = subparsers.add_parser("export", help="Export to Markdown")
    p_export.add_argument("--out", default="backlog.md", help="Output file")

    subparsers.add_parser("plan", help="Calculate and output the DAG diff (plan)")

    subparsers.add_parser(
        "apply", help="Apply the diff and run the SDLC orchestrator loop"
    )

    p_migrate_state = subparsers.add_parser(
        "migrate-state",
        help="Migrate the local execution backlog to the current schema",
    )
    p_migrate_state.add_argument(
        "--retire-legacy",
        action="store_true",
        help="Archive and remove the obsolete .agentic-backlog.json artifact",
    )

    subparsers.add_parser(
        "migrate-ids",
        help="Migrate existing DAG schemas to enforce strict GUID node IDs",
    )

    args = parser.parse_args()

    try:
        if args.command == "init":
            init_cmd(args)
        elif args.command == "add":
            add_cmd(args)
        elif args.command == "update":
            update_cmd(args)
        elif args.command == "status":
            status_cmd(args)
        elif args.command == "block":
            block_cmd(args)
        elif args.command == "unblock":
            unblock_cmd(args)
        elif args.command == "remove":
            remove_cmd(args)
        elif args.command == "prioritize":
            prioritize_cmd(args)
        elif args.command == "next":
            next_cmd(args)
        elif args.command == "export":
            export_cmd(args)
        elif args.command == "plan":
            plan_cmd(args)
        elif args.command == "apply":
            apply_cmd(args)
        elif args.command == "migrate-state":
            migrate_state_cmd(args)
        elif args.command == "migrate-ids":
            migrate_ids_cmd(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
