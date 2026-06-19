"""프로젝트 .venv Python으로 자동 재실행 (시스템 python3 호환)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def ensure_project_venv(*, module_file: Path | None = None) -> None:
    root = Path(__file__).resolve().parents[2]
    venv_dir = root / ".venv"
    venv_python = venv_dir / "bin" / "python"

    if not venv_dir.is_dir() or not venv_python.is_file():
        return
    if Path(sys.prefix).resolve() == venv_dir.resolve():
        return

    if len(sys.argv) >= 3 and sys.argv[1] == "-m":
        argv = [str(venv_python), "-m", sys.argv[2], *sys.argv[3:]]
    elif module_file is not None:
        argv = [str(venv_python), str(module_file.resolve()), *sys.argv[1:]]
    else:
        argv = [str(venv_python), *sys.argv]

    os.execv(str(venv_python), argv)
