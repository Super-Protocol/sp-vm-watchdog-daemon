#!/usr/bin/env python3
import argparse
import re
from pathlib import Path

pattern = re.compile(
    r'^(?P<indent>\s*)import\s+(?P<mod>[A-Za-z_]\w*_pb2)\s+as\s+(?P<alias>[A-Za-z_]\w*)(?P<tail>[ \t]*(#.*)?)$',
    re.MULTILINE,
)


def process(path: Path):
    text = path.read_text(encoding="utf-8")
    new = pattern.sub(r"\g<indent>from . import \g<mod> as \g<alias>\g<tail>", text)
    if new != text:
        path.write_text(new, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Replace 'import X_pb2 as alias' with 'from . import X_pb2 as alias' recursively."
    )
    parser.add_argument("directory", type=Path, help="Directory to process")
    args = parser.parse_args()
    for p in args.directory.rglob("*.py"):
        process(p)


if __name__ == "__main__":
    main()
