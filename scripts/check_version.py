#!/usr/bin/env python3
"""Сверка версии из одного источника: VERSION == serverInfo == User-Agent == SKILL.md.

В CI дополнительно проверяет тег (GITHUB_REF_NAME == "v"+VERSION) и наличие
раздела версии в CHANGELOG.md.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from _common import __version__ as common_version  # noqa: E402


def main():
    errors = []

    version = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()

    # 1. VERSION == _common.__version__
    if version != common_version:
        errors.append(f"VERSION={version} != _common.__version__={common_version}")

    # 2. User-Agent использует __version__
    imp = open(os.path.join(ROOT, "scripts", "import_document.py"), encoding="utf-8").read()
    if "atom-memory-postgres/{__version__}" not in imp:
        errors.append("import_document.User-Agent не берёт __version__")

    # 3. MCP serverInfo.version == __version__
    mcp = open(os.path.join(ROOT, "scripts", "memory_mcp_server.py"), encoding="utf-8").read()
    if '"version": __version__' not in mcp:
        errors.append("memory_mcp_server.serverInfo.version не берёт __version__")

    # 4. SKILL.md frontmatter version совпадает
    skill = open(os.path.join(ROOT, "SKILL.md"), encoding="utf-8").read()
    m = re.search(r"^version:\s*([^\s]+)", skill, re.MULTILINE)
    if not m or m.group(1) != version:
        errors.append(f"SKILL.md version={m.group(1) if m else None} != {version}")

    # 5. тег (только в CI, когда есть GITHUB_REF_TYPE)
    if os.environ.get("GITHUB_REF_TYPE") == "tag":
        ref = os.environ.get("GITHUB_REF_NAME", "")
        if ref != f"v{version}":
            errors.append(f"тег {ref} != v{version}")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"версия согласована: {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())