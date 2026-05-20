#!/usr/bin/env python3
"""Tiny config-reading helper used by the shell scripts.

Usage:
    python3 _config.py CONFIG_PATH KEY [SUBKEY...]

Prints the requested config value (one item per line for lists).
Designed to be cheap and not require PyYAML for simple keys — but YAML is
recommended for full support.

Examples:
    python3 _config.py mystmd/config.yaml chapters.stem
    python3 _config.py mystmd/config.yaml extra_files.stem
    python3 _config.py mystmd/config.yaml source_dir
    python3 _config.py mystmd/config.yaml bibliography
"""

import sys
from pathlib import Path


def load(path: Path):
    text = path.read_text(encoding='utf-8')
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        raise SystemExit("PyYAML required: pip install pyyaml")


def lookup(obj, dotted_key: str):
    """Resolve a.b.c.field. If an intermediate value is a list of dicts,
    return the list of values at the final field."""
    parts = dotted_key.split('.')
    cur = obj
    for i, p in enumerate(parts):
        if isinstance(cur, list):
            # Project field from each dict
            field = '.'.join(parts[i:])
            return [item[field] if isinstance(item, dict) else item for item in cur]
        if cur is None:
            return None
        cur = cur.get(p)
    return cur


def main():
    if len(sys.argv) < 3:
        sys.exit("usage: _config.py CONFIG_PATH KEY")
    config = load(Path(sys.argv[1]))
    result = lookup(config, sys.argv[2])
    if result is None:
        return
    if isinstance(result, list):
        for item in result:
            print(item)
    else:
        print(result)


if __name__ == '__main__':
    main()
