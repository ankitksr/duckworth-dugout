import re
from pathlib import Path

_DIR = Path(__file__).parent
_INCLUDE = re.compile(r"<!--\s*include:(\w+)\s*-->")


def load_prompt(name: str) -> str:
    """Load a prompt template. Resolves `<!-- include:partial -->` markers
    against sibling `_{partial}.md` files before returning, so shared
    snippets (e.g. the canonical availability rule) live in one place.
    """
    text = (_DIR / name).read_text(encoding="utf-8")
    text = _INCLUDE.sub(
        lambda m: (_DIR / f"_{m.group(1)}.md").read_text(encoding="utf-8").strip(),
        text,
    )
    return text.strip()
