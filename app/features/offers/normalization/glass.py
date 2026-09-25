"""The glass a device's screen has: an axis of its own, read the same in every category.

Apple sells an iPad Pro and a MacBook Pro with standard glass or nano-texture glass, two
products at two prices that share every other axis. Its own module, as `colours.py` is,
because a ruleset's fingerprint covers what it imports: tablets and laptops read the glass,
phones do not, and a change here should not recompute every phone.
"""

import re
from typing import Any

from app.features.offers.normalization.rules import Vocabulary

GLASS_KEY = "glass"
STANDARD = "standard"
NANO_TEXTURE = "nano-texture"

# `with standard glass`, `w/Standard Glass`, `Nano-texture glass`: Apple's words, the same
# in every language.
_NANO = re.compile(r"\bnano[-\s]?texture\b", re.IGNORECASE)
_MATTE = re.compile(r"\bmatte\b", re.IGNORECASE)
_APPLE = re.compile(r"^\s*apple\b", re.IGNORECASE)
_GLASS_WORDS = re.compile(
    r"\s*(?:\b(?:w/|with)\s*)?\b(?:standard\s+glass|nano[-\s]?texture(?:\s+glass)?)\b",
    re.IGNORECASE,
)


def the_glass(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The glass on the identity, and no word about it left on the model.

    Nano-texture where the title or the model says so, standard everywhere else: no maker
    but Apple sells another, and a listing of the nano one says it, because it is what the
    price is for. Standard is therefore a reading, not a gap — every device has a glass.
    """
    model = str(fields.get("model") or "").strip()
    title = str(fields.get("title") or "")
    nano = bool(_NANO.search(title) or _NANO.search(model))
    # euronics calls Apple's nano-texture glass `matte`: on 25.09.2026 its three iPad Pros
    # whose part numbers four other shops list as nano-texture read standard for it. Only
    # Apple's — on any other laptop a matte screen is the ordinary anti-glare one.
    if not nano and _APPLE.match(str(fields.get("brand_raw") or "")):
        nano = bool(_MATTE.search(title))
    glass = NANO_TEXTURE if nano else STANDARD
    found: dict[str, Any] = {}
    identity = dict(fields.get("identity") or {})
    if identity.get(GLASS_KEY) != glass:
        found["identity"] = {**identity, GLASS_KEY: glass}
    bare = " ".join(_GLASS_WORDS.sub(" ", model).split())
    if model and bare and bare != model:
        found["model"] = bare
    return found
