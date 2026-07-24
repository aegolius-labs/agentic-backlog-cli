from pathlib import Path
from typing import Any, Dict, Optional


def get_project_root() -> Path:
    """Returns the project root directory."""
    # Assuming src/aio_agentic_sdlc/templating_engine.py
    current_dir = Path(__file__).parent
    return current_dir.parent.parent


def generate_document(
    template_name: str,
    data: Dict[str, Any],
    output_path: str,
    templates_dir: Optional[str] = None,
) -> str:
    """
    Generates a document from a Jinja2 template and writes it to output_path.

    Args:
        template_name: The name of the template file in the templates/ directory.
        data: A dictionary of data to populate the template.
        output_path: The path where the generated document will be saved.
        templates_dir: Optional explicit template directory. When omitted, prefer the current
            working directory's templates folder and then the installed project templates.

    Returns:
        The content of the generated document.
    """
    if templates_dir is not None:
        resolved_templates_dir = Path(templates_dir)
    else:
        cwd_templates = Path.cwd() / "templates"
        if cwd_templates.exists():
            resolved_templates_dir = cwd_templates
        else:
            resolved_templates_dir = get_project_root() / "templates"

    if not resolved_templates_dir.exists():
        raise FileNotFoundError(
            f"Templates directory not found at {resolved_templates_dir}"
        )

    import jinja2.sandbox

    env = jinja2.sandbox.SandboxedEnvironment(
        loader=jinja2.FileSystemLoader(str(resolved_templates_dir)),
        autoescape=jinja2.select_autoescape(["html", "xml"]),
        undefined=jinja2.StrictUndefined,
    )

    try:
        template = env.get_template(template_name)
    except jinja2.TemplateNotFound:
        raise FileNotFoundError(
            f"Template '{template_name}' not found in {resolved_templates_dir}"
        )

    try:
        rendered_content = template.render(**data)
    except jinja2.exceptions.UndefinedError as e:
        raise ValueError(f"Template validation error: missing data field - {str(e)}")

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(rendered_content, encoding="utf-8")

    return rendered_content
