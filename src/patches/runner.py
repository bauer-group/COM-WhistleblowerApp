#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════
# Patches - Runner
# BAUER GROUP | Compliance Reporting Platform
# ═══════════════════════════════════════════════════════════
#
# Lädt alle Patch-Module (Pattern: NNN_name.py) aus dem gleichen Verzeichnis,
# filtert nach APPLIES_WHEN (aktueller Build-Mode via BEHIND_PROXY), und
# führt jede PATCHES-Liste idempotent aus.
#
# Fail-fast: bricht bei Kontext-Mismatch oder fehlendem Ziel ab.
# ═══════════════════════════════════════════════════════════

import importlib
import os
import pathlib
import sys

PATCHES_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(PATCHES_DIR))

from _common import apply  # noqa: E402


def mode_from_env() -> str:
    behind_proxy = os.environ.get("BEHIND_PROXY", "true").strip().lower()
    if behind_proxy == "true":
        return "production"
    if behind_proxy == "false":
        return "development"
    print(f"ERROR: BEHIND_PROXY must be 'true' or 'false', got: {behind_proxy!r}")
    sys.exit(1)


def discover_modules() -> list[str]:
    pattern = "[0-9][0-9][0-9]_*.py"
    return sorted(p.stem for p in PATCHES_DIR.glob(pattern))


def main() -> int:
    mode = mode_from_env()
    print(f"Build mode: {mode} (BEHIND_PROXY={os.environ.get('BEHIND_PROXY', 'true')})")

    modules = discover_modules()
    if not modules:
        print("WARNING: no patch modules found")
        return 0

    failed = False

    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        applies_when = getattr(mod, "APPLIES_WHEN", "always")
        patches = getattr(mod, "PATCHES", [])

        if applies_when not in (mode, "always"):
            print(f"⏭ {mod_name}: skipped (applies only to {applies_when})")
            continue

        if not patches:
            print(f"⏭ {mod_name}: no PATCHES defined")
            continue

        print(f"▶ {mod_name} ({len(patches)} patch{'es' if len(patches) != 1 else ''})")
        for patch in patches:
            result = apply(patch)
            ok = result in ("applied", "already-applied")
            marker = "  ✓" if ok else "  ✗"
            print(f"{marker} {patch['name']}: {result}")
            if not ok:
                failed = True

    if failed:
        print("\nPATCH FAILED — Upstream hat sich geändert oder Patch-Target fehlt.")
        print("Betroffene Patch-Datei in src/patches/ gegen aktuelle Upstream-Version verifizieren.")
        return 1

    print("\nAlle Patches OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
