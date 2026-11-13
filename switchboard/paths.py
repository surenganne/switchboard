"""Private data directory for Switchboard (~/.switchboard, or $SWITCHBOARD_HOME)."""
import os
from pathlib import Path


def home() -> Path:
    p = Path(os.environ.get("SWITCHBOARD_HOME") or Path.home() / ".switchboard")
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    p.chmod(0o700)
    return p


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # create with 0600 from the start so the content is never world-readable
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    path.chmod(0o600)
