"""Copy built dashboard assets into squidbot's packaged static directory.

This helper moves the frontend build output into
`squidbot.adapters.dashboard.static` so installed wheels can serve the UI.
It is used in local packaging workflows and CI gates before wheel creation.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("web/dashboard/dist"),
        help="Path to built frontend dist directory",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=Path("squidbot/adapters/dashboard/static"),
        help="Destination package static directory",
    )
    return parser.parse_args()


def _copy_tree(source: Path, dest: Path) -> None:
    if not source.exists() or not source.is_dir():
        raise FileNotFoundError(f"Dashboard dist directory not found: {source}")

    dest.mkdir(parents=True, exist_ok=True)
    for child in dest.iterdir():
        if child.name == ".gitkeep":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    for child in source.iterdir():
        target = dest / child.name
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)


def main() -> int:
    args = _parse_args()
    _copy_tree(args.source, args.dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
