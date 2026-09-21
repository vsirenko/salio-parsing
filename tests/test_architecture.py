"""The layout rules, enforced rather than only written down.

Vertical slices only stay legible while the import graph points one way. A violation is
cheap to add by accident and expensive to unpick later, so it fails here instead.
"""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"

# Packages that must know nothing about any individual feature.
FEATURE_AGNOSTIC = ("core", "db", "schemas")

# The one feature that exists to serve another. Anything else is a design decision that
# belongs in this dict with a reason, not in a module.
ALLOWED_CROSS_FEATURE = {
    ("users", "rate_limit"): "sign-in counts its own failures",
}


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return {m for m in modules if m.startswith("app.")}


def app_modules() -> list[tuple[Path, set[str]]]:
    return [(p, imported_modules(p)) for p in sorted(APP.rglob("*.py"))]


def test_shared_packages_do_not_know_about_features():
    offences = [
        f"{path.relative_to(APP.parent)} imports {module}"
        for path, modules in app_modules()
        if path.relative_to(APP).parts[0] in FEATURE_AGNOSTIC
        for module in modules
        if module.startswith("app.features.")
    ]
    assert not offences, "core, db and schemas must not depend on a feature:\n" + "\n".join(
        offences
    )


def test_features_do_not_reach_into_each_other():
    offences = []
    for path, modules in app_modules():
        parts = path.relative_to(APP).parts
        if parts[0] != "features":
            continue
        owner = parts[1]
        for module in modules:
            if not module.startswith("app.features."):
                continue
            other = module.split(".")[2]
            if other != owner and (owner, other) not in ALLOWED_CROSS_FEATURE:
                offences.append(f"{path.relative_to(APP.parent)} imports {module}")

    assert not offences, (
        "a feature reached into another one; decide where the code belongs, then add the "
        "pair to ALLOWED_CROSS_FEATURE with the reason:\n" + "\n".join(offences)
    )


def test_every_feature_is_a_package():
    """A loose module under features/ would be invisible to the rules above."""
    loose = (p for p in (APP / "features").iterdir() if p.is_file())
    stray = [p.name for p in loose if p.name != "__init__.py"]
    assert not stray, f"put these in a feature folder: {stray}"
