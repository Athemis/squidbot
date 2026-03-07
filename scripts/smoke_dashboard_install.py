"""Run install-time smoke checks for dashboard assets in a built wheel.

This script creates an isolated virtual environment, installs a selected
`squidbot` wheel, and verifies that packaged dashboard assets are present.
It serves as the final packaging gate used by CI to validate installed-artifact
behavior instead of repository-checkout behavior.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wheel",
        required=True,
        help="Path or glob to built wheel artifact (e.g. dist/*.whl)",
    )
    return parser.parse_args()


def _run(command: list[str], env: dict[str, str], cwd: Path | None = None) -> None:
    subprocess.run(command, check=True, env=env, cwd=str(cwd) if cwd is not None else None)


def main() -> int:
    args = _parse_args()
    matches = sorted(Path().glob(args.wheel))
    if not matches:
        print(f"No wheel found for pattern: {args.wheel}", file=sys.stderr)
        return 2
    wheel = matches[0].resolve()

    with tempfile.TemporaryDirectory(prefix="squidbot-smoke-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        venv_dir = Path(tmp_dir) / "venv"
        _run(["python", "-m", "venv", str(venv_dir)], env=os.environ.copy())

        python_bin = venv_dir / "bin" / "python"
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        _run([str(python_bin), "-m", "pip", "install", str(wheel)], env=env, cwd=tmp_path)

        smoke_code = """
from importlib import resources

from fastapi.testclient import TestClient
from squidbot.adapters.dashboard.api import build_dashboard_app

static_files = resources.files("squidbot.adapters.dashboard.static")
if not (static_files / "index.html").is_file():
    raise SystemExit("Packaged dashboard index.html is missing")

client = TestClient(build_dashboard_app())
response = client.get("/")
if response.status_code != 200:
    raise SystemExit(f"Unexpected status code: {response.status_code}")
if '<div id="app"' not in response.text:
    raise SystemExit("Dashboard index missing app container")
"""

        _run(
            [
                str(python_bin),
                "-c",
                smoke_code,
            ],
            env=env,
            cwd=tmp_path,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
