"""Simple template loading and rendering utilities."""
from pathlib import Path

_TEMPLATE_DIR = Path(__file__).parent


def load_template(name: str) -> str:
    """Load a template file by name."""
    return (_TEMPLATE_DIR / name).read_text(encoding='utf-8')


def render_template(name: str, **kwargs) -> str:
    """Load and render a template with variable substitutions.

    Variables are substituted using {{VARIABLE_NAME}} syntax.
    """
    template = load_template(name)
    for key, value in kwargs.items():
        template = template.replace(f'{{{{{key}}}}}', str(value))
    return template
