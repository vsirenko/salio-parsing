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
    ("offers", "prices"): (
        "ingestion records a price change but does not decide when one counts;"
        " that rule belongs with the table it writes to"
    ),
    # The three below are one reason wearing three hats: a lookup has to canonicalise a
    # value exactly as whoever stored it did, or it misses and reports the catalogue as
    # incomplete. Copying the function would be the bug, so the dependency is deliberate
    # and belongs where it can be seen.
    ("matching", "brands"): "a brand string has to be normalized as brand aliases were",
    ("matching", "catalog"): "a model string has to be normalized as variants were",
    ("matching", "offers"): "the matcher reads the ruleset version that produced a reading",
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


def test_every_feature_documents_itself():
    """A feature folder without a README is one nobody can reason about from outside."""
    missing = [
        p.name
        for p in sorted((APP / "features").iterdir())
        if p.is_dir() and p.name != "__pycache__" and not (p / "README.md").exists()
    ]
    assert not missing, f"these features have no README.md: {missing}"


def test_documented_endpoints_exist():
    """The endpoint tables in a feature README are its contract with the outside.

    Method and path together, not the path alone: documenting a DELETE on a route that
    only answers GET points at a path that exists and still describes something that does
    not. A check that passes on a wrong document is worse than no check.
    """
    import re

    from app.main import app

    METHODS = "GET|POST|PATCH|PUT|DELETE"
    ROW = re.compile(rf"`((?:{METHODS})(?:\s*·\s*(?:{METHODS}))*)\s+(/[\w/{{}}.-]+)`")

    def normalise(path: str) -> str:
        # Parameter names are the README's business; the shape of the path is not.
        return re.sub(r"\{[^}]*\}", "{}", path).rstrip("/")

    live = {
        (method.upper(), normalise(path))
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }

    stale = []
    for readme in sorted((APP / "features").glob("*/README.md")):
        for row in readme.read_text().splitlines():
            if not row.startswith("|"):
                continue
            for methods, path in ROW.findall(row):
                for method in re.split(r"\s*·\s*", methods):
                    if (method, normalise(path)) not in live:
                        stale.append(f"{readme.parent.name}/README.md: {method} {path}")

    assert not stale, "documented endpoints that do not exist:\n" + "\n".join(stale)
