from pathlib import Path

_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    return (_DIR / name).read_text(encoding="utf-8").strip()
