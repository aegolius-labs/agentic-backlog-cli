import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from filelock import FileLock

from .dag_store import guarded_file_path


class TemplateValidationError(ValueError):
    """Raised when caller-provided template data cannot render a document."""


class TemplateNotFoundError(FileNotFoundError):
    """Raised when a requested framework template is unavailable."""


def get_package_templates_dir() -> Path:
    """Return the templates bundled with the installed framework package."""

    return Path(__file__).parent / "templates"


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
        templates_dir: Optional explicit template directory. When omitted, use the templates
            bundled with the installed framework package.

    Returns:
        The content of the generated document.
    """
    if templates_dir is not None:
        resolved_templates_dir = Path(templates_dir)
    else:
        resolved_templates_dir = get_package_templates_dir()

    if not resolved_templates_dir.exists():
        raise TemplateNotFoundError(
            f"Templates directory not found at {resolved_templates_dir}"
        )

    import jinja2.sandbox

    env = jinja2.sandbox.SandboxedEnvironment(
        loader=jinja2.FileSystemLoader(str(resolved_templates_dir)),
        autoescape=jinja2.select_autoescape(["html", "xml"]),
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
    )

    try:
        template = env.get_template(template_name)
    except jinja2.TemplateNotFound:
        raise TemplateNotFoundError(
            f"Template '{template_name}' not found in {resolved_templates_dir}"
        )

    try:
        rendered_content = template.render(**data)
    except jinja2.exceptions.UndefinedError as e:
        raise TemplateValidationError(
            f"Template validation error: missing data field - {str(e)}"
        )

    out_file = guarded_file_path(output_path, create_parent=True)
    lock_file = guarded_file_path(
        out_file.parent / f".{out_file.name}.lock",
        create_parent=True,
    )
    payload = rendered_content.encode("utf-8")
    with FileLock(lock_file, timeout=30, preserve_lock_file=True):
        out_file = guarded_file_path(out_file)
        descriptor, temporary = tempfile.mkstemp(
            dir=out_file.parent,
            prefix=f".{out_file.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            guarded_file_path(out_file)
            os.replace(temporary, out_file)
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)

    return rendered_content
