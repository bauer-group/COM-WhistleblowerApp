# ═══════════════════════════════════════════════════════════
# Patches - Shared Helpers
# BAUER GROUP | Compliance Reporting Platform
# ═══════════════════════════════════════════════════════════

import pathlib


def apply(patch: dict) -> str:
    """
    Idempotent find/replace Patcher.

    patch = {
        "name":   str    — Anzeigename fürs Log
        "target": str    — absoluter Pfad im Image
        "find":   str    — exakte Byte-Sequenz die ersetzt wird
        "replace":str    — Ersatz
    }

    Returns:
        "applied"          → Änderung durchgeführt
        "already-applied"  → Patch bereits im Target (idempotent)
        "MISSING ..."      → Target-Datei fehlt
        "CONTEXT-MISMATCH" → Upstream hat sich geändert, Patch-Kontext alt
    """
    target = pathlib.Path(patch["target"])
    if not target.exists():
        return f"MISSING ({target})"

    content = target.read_text(encoding="utf-8")

    if patch["replace"] in content:
        return "already-applied"

    if patch["find"] not in content:
        return "CONTEXT-MISMATCH (upstream changed?)"

    target.write_text(content.replace(patch["find"], patch["replace"], 1), encoding="utf-8")
    return "applied"
