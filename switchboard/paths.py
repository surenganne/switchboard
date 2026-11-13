"""Private data directory for Switchboard (~/.switchboard, or $SWITCHBOARD_HOME)."""
import hashlib
import os
import re
from pathlib import Path


def home() -> Path:
    p = Path(os.environ.get("SWITCHBOARD_HOME") or Path.home() / ".switchboard")
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    p.chmod(0o700)
    return p


def session_state(session_id) -> Path:
    """Per-session hook state file; the session id never picks a path."""
    sid = str(session_id)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", sid):
        sid = hashlib.sha256(sid.encode()).hexdigest()[:32]
    return home() / "state" / f"{sid}.json"


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # create with 0600 from the start so the content is never world-readable; never write through a symlink
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    path.chmod(0o600)
