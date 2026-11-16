"""Load theme definitions from themes/*.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml

THEMES_DIR = Path(__file__).resolve().parent.parent / "themes"
REQUIRED = ("key", "name", "controls", "references", "control", "direct_classification")


def load_theme(key: str) -> dict:
    path = THEMES_DIR / f"{key}.yaml"
    if not path.exists():
        available = ", ".join(sorted(p.stem for p in THEMES_DIR.glob("*.yaml")))
        raise ValueError(f"No theme called '{key}'. Available: {available}")
    theme = yaml.safe_load(path.read_text())
    missing = [k for k in REQUIRED if k not in theme]
    if missing:
        raise ValueError(f"themes/{key}.yaml is missing: {', '.join(missing)}")
    gt = theme.get("ground_truth")
    refs = {r["ticker"] for g in ("High", "Moderate") for r in theme["references"].get(g, [])}
    if gt and gt in refs:
        raise ValueError(f"themes/{key}.yaml: ground truth {gt} must never be a reference.")
    return theme


def load_all() -> dict[str, dict]:
    return {p.stem: load_theme(p.stem) for p in sorted(THEMES_DIR.glob("*.yaml"))}
