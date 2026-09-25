"""What a laptop listing means, whichever shop it came from.

Written against bigbox's 2501 laptops collected on 24.09.2026. A laptop is not a phone with
a keyboard. A phone of one model differs by storage and colour; a laptop of one model is
sold in dozens of configurations, and the fields a shop fills in name them only coarsely —
bigbox's processor field says `Intel Core Ultra 5` where the title says `226V`, and a
`226V` and a `228V` are two machines at two prices. Over those 2501, eight of bigbox's own
fields together left 1156 listings of 2184 new ones in groups that held more than one
barcode. So the configuration is read from the title as much as from the fields, each axis
by a rule of its own, and a title and a field that disagree about an axis leave it empty.

What tells two laptops of one model apart, decided on 24.09.2026: the exact processor, the
working memory, the storage, the screen to a tenth of an inch, the graphics, the keyboard
layout — an English and a Nordic keyboard are two part numbers and two barcodes, and a buyer
wants the one they can type on — and the colour. The operating system is deliberately not
one: the same machine with Windows Home, Windows Pro or none is one product whose price
varies.
"""

import re
from typing import Any

from app.features.offers.normalization import devices, glass
from app.features.offers.normalization.rules import (
    CATEGORY,
    FINISH,
    Rule,
    Ruleset,
    Vocabulary,
    register,
)

SLUG = "laptops"
VERSION = "laptops-12"

CPU_KEY = "cpu"
RAM_KEY = "ram_mb"
STORAGE_KEY = "storage_mb"
SCREEN_KEY = "screen_inch"
GPU_KEY = "gpu"
KEYBOARD_KEY = "keyboard_layout"
INTEGRATED = "integrated"

_SCALE = {"MB": 1, "GB": 1024, "TB": 1024 * 1024}
_SIZE = r"(\d{1,4}(?:[.,]\d)?)\s?(TB|GB)"

# --- the processor -----------------------------------------------------------------------
# Each shape a shop writes, to one spelling. The number is what identifies the chip — Intel
# and AMD never reuse one inside a family — so the canonical form is the family and the
# number, and whatever a shop adds around them (`Processor`, `®`, `™`, `vPro`) is not in it.
#
# AMD's `AI` is left out of the spelling, because the number already says it: its AI chips
# are the 300s and 400s (`Ryzen AI 7 350`) and the others the 100s and 200s (`Ryzen 7 250`),
# and shops write the first both ways — `Ryzen AI R7-350`, bigbox's field `AMD Ryzen 7` and
# a bare `350`. `PRO` is left out too: it is a different part, but shops do not keep it —
# eleven laptops bigbox and rdveikals share by barcode were `Ryzen 7 350` at one and `Ryzen
# 7 PRO 350` at the other, and a mark nobody keeps cannot tell two laptops apart.
_MARKS = re.compile(r"[®™]|\(R\)|\(TM\)", re.IGNORECASE)
# A table a shop wrote its title as, `AMD Ryzen 5 | 220 | 16 GB`: the family and the number
# in two cells.
_CELLS = re.compile(r"\s*\|\s*")
_INTEL_ULTRA = re.compile(
    # The `X` tier only after `Ultra` itself: `UX5406SA` is an ASUS model, not `U X5 406`.
    r"(?<![\w-])(?:Core\s*)?(?:Ultra\s*(X?[579])|(?:ULT|C?U)([579]))(?:\s*Processor)?\s*[-\s]?\s*(\d{3})"
    r"(?!\s?(?:GB|TB)\b)\s?([A-Z]{0,2})\b(\s+Plus\b)?(?!\s*(?:GB|TB|SSD))",
    re.IGNORECASE,
)
# Intel's Lunar Lake chips all end in `V` and their numbers in 6 or 8 — `226V`, `258V`,
# `288V` — and shops write them `226 V` or drop the letter: `Ultra 7 258`.
_LUNAR_LAKE = re.compile(r"2\d[68]")
_INTEL_CORE_I = re.compile(
    r"\b(?:Core\s*)?i([3579])\s?[-\s]?\s?(\d{4,5}(?:[A-Z]{1,3}\d?)?)\b", re.IGNORECASE
)
# Intel's Core without `Ultra`, 2024 on: `Core 5 120U`, `Core 7 350`, and as shops shorten it,
# `Core 5-210H`, `C5-120U`, and `i5-120U` — an `i` in front of three digits, which is this
# family and not the old one, whose numbers have four or five.
_INTEL_CORE_N = re.compile(
    r"(?<![\w-])(?:Core\s?|C|i)([3579])\s?-?\s?(\d{3}[A-Z]{0,2})\b(?!\s*(?:GB|TB|Hz|nits|SSD))",
    re.IGNORECASE,
)
_INTEL_N = re.compile(r"\b(?:Intel\s+)?(?:Processor\s+)?(N\d{2,3})\b")
_INTEL_CELERON = re.compile(
    r"\b(Celeron|Pentium(?:\s+Silver|\s+Gold)?)\s+(N?\d{4}[A-Z]?)\b", re.IGNORECASE
)
# `Ryzen 7 7735HS`, `Ryzen AI 7 350`, `R7-260`, `R7 Ai 350`, Dell's `AR5-8540U`, `9955HX3D`.
# Not inside a maker's code: ASUS's `FA608UP-R7165W` has an `R7 165W` in it.
_RYZEN = re.compile(
    r"(?<![\w-])(?:Ryzen\s?(?:AI\s?)?|(?:AI\s?)?A?R|AI\s)([3579])\s?(?:AI\s?)?[-\s]?\s?((?:(?:PRO|HX)\s?){0,2})"
    r"(\d{3,4}(?:[A-Z]{1,3}\d?[A-Z]?)?)\b",
    re.IGNORECASE,
)
_ATHLON = re.compile(r"\bAthlon(?:\s+(?:Silver|Gold))?\s+(\d{4}[A-Z]{0,2})\b", re.IGNORECASE)
_KOMPANIO = re.compile(r"\bKompanio\s?(\d{3,4}[A-Z]?)\b", re.IGNORECASE)
_INTEL_U = re.compile(r"(?<![\w-])(U3\d{2}E?)\b")
# `Ryzen Al 7 350`: a lowercase L where the I should be, in the shop's own field.
_AI_TYPO = re.compile(r"\bAl(?=\s?\d)")
_RYZEN_AI_MAX = re.compile(r"\bAI\s?MAX(\+?)\s?(?:PRO\s)?(\d{3})\b", re.IGNORECASE)
_APPLE_M = re.compile(r"\bM([1-5])(?:\s+(Pro|Max|Ultra))?\b")
_APPLE_A = re.compile(r"\bA(1[5-9])(\s?Pro)?\b")
# `X1E-78-100`, `X1P-42-100`, `X1-26-100`, `X1 26 100`. The letter is left out of the
# spelling: some shops drop it and the two numbers after it already say which chip.
_SNAPDRAGON = re.compile(r"\bX([12])[EP]?[-\s](\d{2})[-\s](\d{3})\b", re.IGNORECASE)
# The family a coarse field names — bigbox's `AMD Ryzen 7`, `Intel Core 7 / i7`, `Intel Core
# Ultra 5` — which a bare number in the title completes: `… 16 FHD+ IPS 150U 16 GB …`.
_FAMILY = re.compile(
    r"^\s*(?:(?P<ultra>Intel\s+Core\s+Ultra\s+(?P<ut>X?[579]))"
    r"|(?P<core>Intel\s+Core\s+i?(?P<ct>[3579])(?:\s*/\s*i[3579])?)"
    r"|(?P<ryzen>AMD\s+Ryzen\s+(?:AI\s+)?(?P<rt>[3579])(?:\s+PRO)?))\s*$",
    re.IGNORECASE,
)
# A number on its own that could be a processor's: not a size, a rate, a resolution or a
# part number, which is what a bare three digits usually are.
_BARE = re.compile(
    r"(?<![\w.,/-])(\d{3,5}(?:[A-Z]{1,3}\d?)?)(?![\w.]|,\d)(?!\s*(?:GB|TB|MB|Hz|nits|W\b|mm|MHz|x\s?\d|SSD|HDD|eMMC|NVMe|UFS))",
    re.IGNORECASE,
)


_MAKERS = {"intel", "amd", "apple", "qualcomm"}


def processors(text: str) -> set[str]:
    """Every processor the text names, each in its canonical spelling."""
    text = _AI_TYPO.sub("AI", _CELLS.sub(" ", _MARKS.sub("", text)))
    found: set[str] = set()
    for full, short, number, suffix, plus in _INTEL_ULTRA.findall(text):
        tier = full or short
        if not suffix and _LUNAR_LAKE.fullmatch(number):
            suffix = "V"
        # `290HX Plus` is a chip of its own; there is no `290HX`.
        found.add(
            f"Intel Core Ultra {tier.upper()} {number}{suffix.upper()}{' Plus' if plus else ''}"
        )
    for tier, number in _INTEL_CORE_I.findall(text):
        found.add(f"Intel Core i{tier}-{number.upper()}")
    for tier, number in _INTEL_CORE_N.findall(text):
        found.add(f"Intel Core {tier} {number.upper()}")
    for number in _INTEL_N.findall(text):
        found.add(f"Intel {number.upper()}")
    for family, number in _INTEL_CELERON.findall(text):
        found.add(f"Intel {' '.join(family.title().split())} {number.upper()}")
    for plus, number in _RYZEN_AI_MAX.findall(text):
        found.add(f"AMD Ryzen AI Max{plus} {number}")
    if not _RYZEN_AI_MAX.search(text):
        for tier, _marks, number in _RYZEN.findall(text):
            # A three-digit Ryzen has no suffix — `Ryzen AI 7 350` — and shops add one:
            # `AI 7-350H`.
            if re.fullmatch(r"\d{3}[A-Z]+", number):
                number = number[:3]
            found.add(f"AMD Ryzen {tier} {number.upper()}")
    if re.search(r"\b(?:Apple|MacBook)\b", text, re.IGNORECASE):
        for generation, grade in _APPLE_M.findall(text):
            found.add(f"Apple M{generation}{f' {grade.title()}' if grade else ''}")
        for generation, pro in _APPLE_A.findall(text):
            found.add(f"Apple A{generation}{' Pro' if pro else ''}")
    for number in _ATHLON.findall(text):
        found.add(f"AMD Athlon {number.upper()}")
    for number in _KOMPANIO.findall(text):
        found.add(f"MediaTek Kompanio {number.upper()}")
    if re.search(r"\bIntel\b", text, re.IGNORECASE):
        for number in _INTEL_U.findall(text):
            found.add(f"Intel {number.upper()}")
    for series, first, second in _SNAPDRAGON.findall(text):
        found.add(f"Qualcomm Snapdragon X{series}-{first}-{second}")
    return {_in_intel_s_scheme(chip) for chip in found}


# Intel's current names say by their number which line a chip is: an Ultra's ends in 5, 6 or
# 8 — `225U`, `226V`, `258V`, `355`, `386H` — and a plain Core's in 0 — `120U`, `150U`, `210H`,
# `350`. Shops write the one for the other: across the barcodes bigbox and rdveikals share,
# `Core 5 225U` and `Core Ultra 5 225U` named one laptop, and `Core 9 275HX` was the Ultra.
# The exception is `290HX Plus`, an Ultra ending in 0, which is why a number ending in 0 with
# `HX` and no `Plus` is left as written.
_NEW_INTEL = re.compile(r"^Intel Core (?:Ultra )?(X?[3579]) (\d{3})([A-Z]{0,2}(?: Plus)?)$")


def _in_intel_s_scheme(chip: str) -> str:
    found = _NEW_INTEL.match(chip)
    if found is None:
        return chip
    tier, number, suffix = found.groups()
    if (number[-1] not in "0568" or suffix == "HX") and not suffix.endswith("Plus"):
        # A number the scheme says nothing about: kept as the shop wrote it.
        return chip
    ultra = number[-1] in "568" or suffix.endswith("Plus") or tier.startswith("X")
    # The 2026 chips ending in 8 with `H` are the `X` tier — `X7 358H`, `X9 388H` — and
    # Lenovo's `ULT9-388H` drops the letter.
    if re.fullmatch(r"3\d8", number) and suffix == "H" and not tier.startswith("X"):
        tier = f"X{tier}"
    return f"Intel Core {'Ultra ' if ultra else ''}{tier} {number}{suffix}"


_STORAGE_SIZES = {"128", "256", "512"}
# A chip's number standing as an item of the title's list — `…, 226V, 16 GB, …`, `| 260 |` —
# or carrying its letter anywhere. A bare three digits elsewhere is too often a name:
# `HP 250 G10` is a laptop, not a Ryzen 7 250.
_LISTED = re.compile(r"(?:^|[,|/]\s*)(\d{3,5}[A-Z]{0,3}\d?)(?=\s*(?:[,|/]|$))", re.IGNORECASE)
_LETTERED = re.compile(r"(?<![\w.,/-])(\d{3,5}[A-Z]{1,3}\d?)(?![\w.]|,\d)", re.IGNORECASE)


def _known_by_its_number(title: str, vocabulary: Vocabulary) -> set[str]:
    """The one chip the registry knows by a number the title states, and no field named.

    1a's index states no processor family at all — `Lenovo ThinkPad T14 G6, 226V, 16 GB` —
    and a chip's number is its identity: `226V` is only ever the Core Ultra 5 226V. Which
    chip a number is belongs to the registry, where each chip is entered with its number as
    an alias wherever that number is one chip's alone.
    """
    text = _CELLS.sub(" | ", _MARKS.sub("", title))
    numbers = set(_LISTED.findall(text)) | set(_LETTERED.findall(text))
    known = {vocabulary.value_of(CPU_KEY, number) for number in numbers - _STORAGE_SIZES}
    known.discard(None)
    return known if len(known) == 1 else set()


def _completed(family: str, title: str) -> set[str]:
    """A coarse family from a field, completed by the one bare number in the title that fits."""
    shape = _FAMILY.match(_MARKS.sub("", family))
    if shape is None:
        return set()
    text = _CELLS.sub(" ", _MARKS.sub("", title))
    # `226 V`, spaced off its letter, is one number.
    text = re.sub(r"\b(\d{3})\s(V|U|H|HX)\b", r"\1\2", text)
    # A storage size written without its unit is never a chip: `… 16 GB 512 SSD`, `/512/`.
    numbers = {n.upper() for n in _BARE.findall(text)} - _STORAGE_SIZES
    if shape["ultra"]:
        fits = {
            f"Intel Core Ultra {shape['ut']} {n}{'V' if _LUNAR_LAKE.fullmatch(n) else ''}"
            for n in numbers
            if re.fullmatch(r"\d{3}[A-Z]{0,2}", n)
        }
    elif shape["core"]:
        fits = {
            f"Intel Core i{shape['ct']}-{n}"
            for n in numbers
            if re.fullmatch(r"\d{4,5}[A-Z]{1,3}\d?", n)
        }
        fits |= {f"Intel Core {shape['ct']} {n}" for n in numbers if re.fullmatch(r"\d{3}[UH]", n)}
    else:
        fits = {
            f"AMD Ryzen {shape['rt']} {n}"
            for n in numbers
            if re.fullmatch(r"\d{4}[A-Z]{1,2}|[1-4]\d{2}", n)
        }
    return {_in_intel_s_scheme(chip) for chip in fits} if len(fits) == 1 else set()


def _cpu(payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary) -> dict[str, Any]:
    """The one processor the title and the fields name, or nothing.

    A field is often coarser than the title — `Apple M5` beside `Apple M5 Max`, `AMD Ryzen 7`
    beside `Ryzen 7 260` — and a coarser name is not a disagreement: a name another one
    begins with gives way to it.
    """
    title = str(fields.get("title") or "")
    named = processors(title)
    families: list[str] = []
    for name, value in (fields.get("attributes") or {}).items():
        if vocabulary.attribute_key(str(name)) == CPU_KEY:
            named |= processors(str(value))
            families.append(str(value))
    if not named:
        for family in families:
            named |= _completed(family, title)
    if not named:
        named = _known_by_its_number(title, vocabulary)
    named = {n for n in named if not any(o != n and o.startswith(n + " ") for o in named)}
    if len(named) != 1:
        return {}
    chip = named.pop()
    # A field naming another maker's chips is a disagreement, however sure the title looks:
    # bigbox files two Intel ThinkPads, `ULT7-355 … Intel Graphics`, as `AMD Ryzen 7`.
    makers = {family.split()[0].casefold() for family in families if family.split()}
    if makers & _MAKERS and chip.split()[0].casefold() not in makers:
        return {}
    return _axis(fields, CPU_KEY, chip)


# A shop's model repeating its series — `Ryzen 7` then `Ryzen 7 260` — said once.
_REPEATED = re.compile(r"\b(\w+(?:\s+\w+){0,2})\s+\1\b", re.IGNORECASE)


def chip_from_fields(texts: list[str], fields: dict[str, Any]) -> dict[str, Any]:
    """The chip several of a shop's fields name together, checked against the reading.

    rdveikals, euronics and bm each split the chip over fields that name nothing alone —
    maker, series, model: `Intel`, `Core Ultra 7`, `255H`. Joined, they are this category's
    spelling of the chip. A coarser name gives way to a finer one either way round; two
    chips leave the axis empty.
    """
    chips = processors(_REPEATED.sub(r"\1", " ".join(t.strip() for t in texts if t)))
    if len(chips) != 1:
        return {}
    chip = chips.pop()
    identity = dict(fields.get("identity") or {})
    read = identity.get(CPU_KEY)
    if read == chip or (read and read.startswith(chip + " ")):
        return {}
    if read is None or chip.startswith(read + " "):
        return {"identity": {**identity, CPU_KEY: chip}}
    identity.pop(CPU_KEY)
    return {"identity": identity}


# --- memory and storage -------------------------------------------------------------------
# Working memory, as a title marks it: `16GB RAM`, `RAM 16GB`, `32GB LPDDR5X`, `16 GB DDR5`.
_RAM_MARKED = re.compile(
    _SIZE + r"\s*(?:\(\d+\s?x\s?\d+\s?GB\)\s*)?(?:(?:LP)?DDR\d\w*|RAM|Unified)\b"
    r"|\bRAM\s*:?\s*" + _SIZE,
    re.IGNORECASE,
)
# Storage, as a title marks it: `512GB SSD`, `SSD 512GB`, `SSD1TB`, `SSD512`, `1TB NVMe`.
_STORAGE_MARKED = re.compile(
    _SIZE + r"\s*(?:M\.2\s*)?(?:PCIe\s*)?(?:NVMe\s*)?(?:SSD|eMMC|HDD|NVMe|UFS)\b"
    r"|\b(?:SSD|eMMC|NVMe)\s*:?\s*(\d{1,4})\s?(TB|GB)?\b",
    re.IGNORECASE,
)
# A size with no unit, glued to its kind: `512SSD`, `512 SSD`, and one distributor's `1 SSD`
# for a terabyte. One digit is terabytes; no laptop has shipped with 8 GB of storage since
# the netbooks.
_STORAGE_BARE = re.compile(r"\b(\d{1,4})\s?(?:SSD|HDD|eMMC)\b", re.IGNORECASE)
# Memory in gigabytes written directly in front of the storage: `16GB/512SSD`, `32 GB 1 SSD`,
# `32GB SSD1TB` — but not `512 GB SSD`, which is the storage itself.
_RAM_BEFORE_STORAGE = re.compile(
    r"\b(\d{1,3})\s?GB\s*[/,]?\s*(?=(?:\d{1,4}\s?(?:GB|TB)?\s?)(?:SSD|HDD|eMMC|NVMe)\b|SSD\s?\d)",
    re.IGNORECASE,
)
# `16GB/512GB`, `16/512GB`, `32GB/1TB`: memory, then storage. The only place the order says
# which is which, and every shop that writes a pair writes it this way round.
_PAIR = re.compile(
    r"\b(\d{1,3})\s?(?:GB)?\s?/\s?(\d{3,4}|[1-8])\s?(GB|TB)\b(?!\s*/\s*\d)", re.IGNORECASE
)


def megabytes(amount: str, unit: str) -> int:
    """A size in megabytes, the binary way: `512GB` is 524288.

    A whole number of thousands of gigabytes is that many terabytes. Drives are sold in
    decimal terabytes and a shop that writes `1000 GB` means the same drive as one writing
    `1 TB`; read literally the two were 1024000 and 1048576 MB — one MacBook as two entries,
    on 58 of euronics' listings and 3 of bm's on 25.09.2026.
    """
    value = float(amount.replace(",", "."))
    if unit.upper() == "GB" and value >= 1000 and value % 1000 == 0:
        value, unit = value / 1000, "TB"
    return int(value * _SCALE[unit.upper()])


def _stated(fields: dict[str, Any], vocabulary: Vocabulary, key: str) -> set[int]:
    sizes: set[int] = set()
    for name, value in (fields.get("attributes") or {}).items():
        if vocabulary.attribute_key(str(name)) != key:
            continue
        # `1 TB + 2TB` is two drives, and neither of them is the laptop's storage alone.
        if "+" in str(value):
            continue
        found = re.search(_SIZE, str(value), re.IGNORECASE)
        if found:
            sizes.add(megabytes(*found.groups()))
    return sizes


def _titled_ram(title: str) -> set[int]:
    sizes = {megabytes(a or c, b or d) for a, b, c, d in _RAM_MARKED.findall(title)}
    for memory, _, _ in _PAIR.findall(title):
        sizes.add(megabytes(memory, "GB"))
    for memory in _RAM_BEFORE_STORAGE.findall(title):
        sizes.add(megabytes(memory, "GB"))
    return sizes


def titled_storage(title: str) -> set[int]:
    sizes: set[int] = set()
    for a, b, c, d in _STORAGE_MARKED.findall(title):
        if a:
            sizes.add(megabytes(a, b))
        elif c:
            # `SSD512` names no unit; a laptop's storage in gigabytes is three digits or four.
            sizes.add(megabytes(c, d or ("TB" if len(c) == 1 else "GB")))
    for _, storage, unit in _PAIR.findall(title):
        sizes.add(megabytes(storage, unit))
    if not sizes:
        for amount in _STORAGE_BARE.findall(title):
            sizes.add(megabytes(amount, "TB" if len(amount) == 1 else "GB"))
    return sizes


def _one(stated: set[int], titled: set[int]) -> int | None:
    """The one size both sources agree on; either alone if the other is silent."""
    sources = [s for s in (stated, titled) if s]
    if not sources:
        return None
    agreed = set.intersection(*sources)
    return agreed.pop() if len(agreed) == 1 and all(len(s) == 1 for s in sources) else None


def _ram(payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary) -> dict[str, Any]:
    size = _one(_stated(fields, vocabulary, RAM_KEY), _titled_ram(str(fields.get("title") or "")))
    return _axis(fields, RAM_KEY, size) if size else {}


def _storage(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    size = _one(
        _stated(fields, vocabulary, STORAGE_KEY), titled_storage(str(fields.get("title") or ""))
    )
    return _axis(fields, STORAGE_KEY, size) if size else {}


# --- the screen ---------------------------------------------------------------------------
_INCHES = re.compile(
    r"(?<![\d.,])(\d{2}(?:[.,]\d{1,2})?)\s*(?:\"|''|”|″|-?\s?inch(?:es)?\b|\s?in\b|\s?Zoll\b|\s?colių\b)",
    re.IGNORECASE,
)
_CENTIMETRES = re.compile(r"(?<![\d.,])(\d{2}(?:[.,]\d{1,2})?)\s?cm\b", re.IGNORECASE)
_SMALLEST, _LARGEST = 10.0, 19.0


def _tenth(value: float) -> float | None:
    rounded = round(value, 1)
    return rounded if _SMALLEST <= rounded <= _LARGEST else None


def _screens(text: str) -> set[float]:
    found = {_tenth(float(n.replace(",", "."))) for n in _INCHES.findall(text)}
    if not found - {None}:
        # Only where the text gives no inches: `39,62 cm (15,6")` states both, and the
        # inches in the bracket are the maker's own figure.
        found = {_tenth(float(n.replace(",", ".")) / 2.54) for n in _CENTIMETRES.findall(text)}
    return found - {None}


def _screen(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    stated: set[float] = set()
    for name, value in (fields.get("attributes") or {}).items():
        if vocabulary.attribute_key(str(name)) != SCREEN_KEY:
            continue
        bare = re.fullmatch(r"\s*(\d{2}(?:[.,]\d{1,2})?)\s*(?:\"|''|”|in|inch)?\s*", str(value))
        stated |= (
            {_tenth(float(bare.group(1).replace(",", ".")))} - {None}
            if bare
            else _screens(str(value))
        )
    titled = _screens(str(fields.get("title") or ""))
    sources = [s for s in (stated, titled) if s]
    if not sources or any(len(s) != 1 for s in sources):
        return {}
    sizes = {next(iter(s)) for s in sources}
    if len(sizes) == 2:
        # A maker names a screen by the whole inch below it — Apple's `MacBook Air 13"` is
        # 13.6, its `15"` 15.3 — so a whole number and a size within that inch are one
        # screen, and the exact one is kept.
        low, high = sorted(sizes)
        if low == int(low) and low < high < low + 1:
            sizes = {high}
    return _axis(fields, SCREEN_KEY, sizes.pop()) if len(sizes) == 1 else {}


# --- graphics -----------------------------------------------------------------------------
_RTX = re.compile(r"\bRTX\s?(\d{4})(\s?Ti)?\b(?!\s*Ada)", re.IGNORECASE)
_RTX_A = re.compile(r"\bRTX\s?(A\d{3,4})\b", re.IGNORECASE)
_GTX = re.compile(r"\bGTX\s?(\d{4})(\s?Ti)?\b", re.IGNORECASE)
_RADEON_RX = re.compile(r"\bRX\s?(\d{4}[MS]?)\b", re.IGNORECASE)
_ARC_DISCRETE = re.compile(r"\bArc\s?(A\d{3}M)\b", re.IGNORECASE)
# Graphics on the processor, as a title names it: Lenovo's `/INT/` slot, `Intel Graphics`,
# `Intel UHD`, `Iris Xe`, `Arc 140V`, `Radeon 610M`, `Radeon Graphics`, `Adreno`.
_INTEGRATED_SLOT = re.compile(
    r"/\s?INT\s?/|\bIntel\s+(?:UHD|Iris|Graphics)\b|\bIris\s?Xe\b|\bArc\s+(?:Graphics|1[34]0[VT])\b"
    r"|\bRadeon\s+(?:\d{3}M|Graphics)\b|\bAdreno\b",
    re.IGNORECASE,
)
# Chips that have no discrete graphics beside them at all.
_NO_DISCRETE = ("Apple ", "Qualcomm ")
# The vendors whose graphics share the processor's die. A listing naming only one of these
# and no discrete card has the processor's graphics.
# The vendors, and the names of graphics that are the processor's own, written with or
# without the vendor: euronics' `UHD Graphics`, `Radeon`, `Iris Xe Graphics`.
_ON_THE_PROCESSOR = re.compile(
    r"^\s*(?:Intel|AMD\s+Radeon|Apple|Qualcomm|UHD|Iris|Arc\s+Graphics|Radeon(?!\s+RX)|Adreno)\b",
    re.IGNORECASE,
)


def _discrete(text: str) -> set[str]:
    found: set[str] = set()
    for number, ti in _RTX.findall(text):
        # A four-digit RTX number below 2000 is a workstation part named `RTX PRO 1000`.
        if not re.search(rf"\bRTX\s?PRO\s?{number}\b", text, re.IGNORECASE):
            found.add(f"NVIDIA GeForce RTX {number}{' Ti' if ti else ''}")
    for number in re.findall(r"\bRTX\s?PRO\s?(\d{3,4})\b", text, re.IGNORECASE):
        found.add(f"NVIDIA RTX PRO {number}")
    # `RTX 500 Ada` is the 2023 workstation part and `RTX PRO 500` the 2025 one: two cards.
    for number in re.findall(r"\bRTX\s?(\d{3,4})\s?Ada\b", text, re.IGNORECASE):
        found.add(f"NVIDIA RTX {number} Ada")
    for number in _RTX_A.findall(text):
        found.add(f"NVIDIA RTX {number.upper()}")
    for number, ti in _GTX.findall(text):
        found.add(f"NVIDIA GeForce GTX {number}{' Ti' if ti else ''}")
    for number in _RADEON_RX.findall(text):
        found.add(f"AMD Radeon RX {number.upper()}")
    for number in _ARC_DISCRETE.findall(text):
        found.add(f"Intel Arc {number.upper()}")
    return found


def _gpu(payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary) -> dict[str, Any]:
    """A discrete card by its model, `integrated` where a source says the processor's."""
    title = str(fields.get("title") or "")
    cards = _discrete(title)
    on_the_processor = bool(_INTEGRATED_SLOT.search(title))
    for name, value in (fields.get("attributes") or {}).items():
        if vocabulary.attribute_key(str(name)) != GPU_KEY:
            continue
        text = str(value)
        stated = _discrete(text)
        cards |= stated
        if not stated and _ON_THE_PROCESSOR.search(text):
            on_the_processor = True
    # A coarser name gives way to the one that begins with it: bigbox's field says `RTX
    # 5070` where the title says `RTX 5070 Ti`.
    cards = {c for c in cards if not any(o != c and o.startswith(c + " ") for o in cards)}
    if len(cards) == 1:
        return _axis(fields, GPU_KEY, cards.pop())
    chip = str((fields.get("identity") or {}).get(CPU_KEY) or "")
    if not cards and (on_the_processor or chip.startswith(_NO_DISCRETE)):
        return _axis(fields, GPU_KEY, INTEGRATED)
    return {}


# --- the keyboard -------------------------------------------------------------------------
# A layout as a title marks it: the word in front of `kbd`, `Kb` or `keyboard`, with the
# shop's `Backlit` between — `Pro/ENG Backlit kbd`, `BT/US Kb`, `Nordic keyboard`. The marker
# is what makes a bare `ENG` a keyboard; Lenovo's `/INT/` slot is its graphics.
_KEYBOARD_MARKED = re.compile(
    r"(?:^|[\s/,(])([^\W\d_]{2,12})\s+(?:Back?lit\s+)?(?:kbd|kb|keyboard)\b", re.IGNORECASE
)


# A remark after a layout, `ENG (ar apgaismojumu)` — "with a backlight" — and the separator of
# a keyboard printed for two languages, `ENG / RUS`, `NOR/ENG`.
_REMARK = re.compile(r"\([^)]*\)")
_BOTH = re.compile(r"\s*/\s*")


def keyboard_word(vocabulary: Vocabulary, word: str) -> str | None:
    """The layout a shop's word for one means, through the registry.

    A keyboard printed for two languages is a layout of its own — `ENG / RUS` is not the
    English keyboard — so each half is resolved and the two are named together, `english+
    russian`. A half the registry does not know makes the whole unknown.
    """
    halves = [h for h in _BOTH.split(_REMARK.sub(" ", word).strip()) if h.strip()]
    if not halves:
        return None
    meant = [vocabulary.value_of(KEYBOARD_KEY, half.strip()) for half in halves]
    if None in meant:
        return None
    return "+".join(sorted(set(meant)))


def _keyboard(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The layout the fields and the title state, through the registry's words for them."""
    said = {
        meant
        for name, value in (fields.get("attributes") or {}).items()
        if vocabulary.attribute_key(str(name)) == KEYBOARD_KEY
        and (meant := keyboard_word(vocabulary, str(value)))
    }
    for word in _KEYBOARD_MARKED.findall(str(fields.get("title") or "")):
        if meant := keyboard_word(vocabulary, word):
            said.add(meant)
    return _axis(fields, KEYBOARD_KEY, said.pop()) if len(said) == 1 else {}


# --- the model ----------------------------------------------------------------------------
# Where the name stops and the configuration begins. The configuration's words are the
# industry's, not a language's: a panel (`FHD`, `WUXGA`, `OLED`, `IPS`), a size with its
# unit, a processor, an operating system (`W11`, `Win11`).
_CONFIGURATION = re.compile(
    r"\s[-–]\s|[,|/(]|\s\d{1,2}(?:[.,]\d{1,2})?\s?(?:\"|''|”|″|-?inch|collu|collas|cm\b)"
    r"|\b\d{1,4}\s?(?:GB|TB)\b|\b(?:FHD|WUXGA|WQXGA|QHD|UHD|OLED|IPS|2\.?[58]K|3K|4K|HD\+?|WXGA)\b"
    r"|\b(?:AG|AR|Touch|Anti-?glare)\b"
    # A refresh rate, `120hz`, and a diagonal written bare, `15.6`: rdveikals names the screen
    # with neither a unit nor a separator — `Dell Pro 15 Essential PV15250 15.6 FHD` — and
    # only the `GB` of the memory used to stop the name, 836 of its 1440 models running on
    # into `15.6 120hz 7520U`. A whole inch stays: `Pro 14` is a name. With a point only: a
    # comma is already a separator, and `LOQ 15AHP10 15,6` cut at the comma keeps the `15`
    # the other shops call it by, where cut at the number it came out `LOQ`.
    r"|\b\d{2,3}\s?Hz\b|\s\d{2}\.\d\b"
    # The diagonal run into the panel, `Inspiron 14 Plus 14FHD+`.
    r"|\b\d{2}(?:FHD|QHD|UHD|WUXGA|WQXGA|OLED)\+?"
    r"|\b(?:W1[01]\w*|Win\s?1[01]\w*|Windows|NoOS|FreeDOS|DOS)\b"
    # A processor. `Ultra` alone is a name — `OmniBook Ultra Flip`, `ZBook Ultra G1a` — and is
    # a processor only with its tier after it.
    r"|\b(?:Intel|AMD|Ryzen|Snapdragon|Celeron|Pentium|Apple\s+[MA]\d{1,2})\b"
    r"|\bCore\s?(?:i\d|Ultra|\d)|\bUltra\s?X?[3579]\b|\b[CU][3579]\s\d{3}",
    re.IGNORECASE,
)
# A maker's code for one configuration, which some shops write into the name and others do
# not: `21QG006FMH`, `X1504VA-BQ4296W`, `FA607NUQ-RL014`, `PV14250`, `83ES001GLT`, MEDION's
# `30039679`. Letters and digits mixed, six characters or more, or six digits; `T14`, `X1`,
# `G14` and `V15` are names and shorter.
_CODE = re.compile(r"^(?:(?=[\w-]*\d)(?=[\w-]*[A-Za-z])[\w-]{6,}|\d{6,})$")
# The quotes a shop puts round a name, `„Dell Pro Max 16 Plus“`; not `"` or `”`, which are inches.
_QUOTES = "\u201e\u201c\u00ab\u00bb"
# A straight quote that opens a name (before a letter) or closes one (after a letter); an inch
# mark follows a digit and is left for the size rule.
_NAME_QUOTE = re.compile(r'(?:(?<=^)|(?<=\s))"(?=[A-Za-z])|(?<=[A-Za-z])"(?=\s|$)')


def _model_from_title(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The name in front of the configuration, without the kind of thing, the maker or a code."""
    if fields.get("model"):
        return {}
    title = str(fields.get("title") or "")
    for quote in _QUOTES:
        title = title.replace(quote, " ")
    # A straight quote opening or closing a name, `"Dell Pro 14 Essential"` — after a letter or
    # before one, where an inch mark stands after a digit. bigbox's titles open with one on 64
    # of 2129, and the name kept it: `"Dell Pro 14` became an entry of its own.
    title = _NAME_QUOTE.sub(" ", title)
    brand = str(fields.get("brand_raw") or "").strip().casefold()
    # `___Pro 14 Plus`: underscores a shop left in front of a word, never part of it. And the
    # closing quote of a quoted name that ends in a code, `"Dell 15 DC15250"`: after a digit it
    # reads as an inch mark, but a word with letters in it is no size.
    words = [
        word.lstrip("_").rstrip('"') if re.search(r"[A-Za-z]", word) else word.lstrip("_")
        for word in title.split()
        if word.lstrip("_")
    ]
    while words and (
        words[0].strip(",.").casefold() in vocabulary.category_names or words[0].casefold() == brand
    ):
        words = words[1:]
    head = " ".join(words)
    cut = _CONFIGURATION.search(head)
    if cut:
        head = head[: cut.start()]
    kept = [w for w in head.split() if not _CODE.match(w)]
    while kept and kept[-1].strip(",.").casefold() in vocabulary.category_names:
        kept = kept[:-1]
    # The diagonal written again after the name — `Dell Pro 14 14 FHD+`, `Dell 16 Plus 16`,
    # `TUF Gaming A14 14` — when the name already carries the number, as a word or inside one,
    # or when it follows a model number, `Latitude 5420 14`. `Pro 14` alone keeps it, because
    # there it is the name; so does `Pro Precision 5 14`, where the number before it is one
    # digit. A screen of 15.6 is written `15` as often as not, so the whole inch counts.
    screen = (fields.get("identity") or {}).get(SCREEN_KEY)
    if (
        len(kept) > 1
        and kept[-1].isdigit()
        and (screen is None or int(kept[-1]) == int(float(screen)) or kept[-1] == kept[-2])
        and (
            any(kept[-1] in word for word in kept[:-1]) or sum(ch.isdigit() for ch in kept[-2]) >= 3
        )
    ):
        kept = kept[:-1]
    model = " ".join(kept).strip(" -–,")
    return {"model": model[:200]} if model else {}


def _without_a_trailing_colour(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """A colour the registry knows off the end of the model, however the model was found.

    dateks's `Modelis` field carries it — `ThinkPad P16 Gen 3 Black`, `Pro 16 Platinum
    Silver` — on 52 of its 709 laptops, and the colour is an axis of its own: kept in the
    name, one model became an entry per colour. A phrase is tried before its last word, so
    `Ice Blue` goes whole where the registry knows it and is left whole where it does not;
    never the last word left, which would be a shop's mistake to see.
    """
    model = (fields.get("model") or "").strip()
    if not model or not vocabulary.colours:
        return {}
    words = model.split()
    while len(words) > 1:
        for length in (3, 2, 1):
            if len(words) > length and (
                " ".join(words[-length:]).strip(",.").casefold() in vocabulary.colours
            ):
                words = words[:-length]
                break
        else:
            break
    shorter = " ".join(words)
    return {"model": shorter} if shorter != model else {}


def _axis(fields: dict[str, Any], key: str, value: Any) -> dict[str, Any]:
    return {"identity": {**fields.get("identity", {}), key: value}}


RULESET = register(
    CATEGORY,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="laptops-color",
                layer=CATEGORY,
                why=(
                    "A MacBook Pro in Space Black and in Silver are two barcodes, and the"
                    " first bigbox run filed them as one entry before colour was an axis. A"
                    " shop's colour field, resolved through the registry, as for a phone."
                ),
                body=devices.color,
            ),
            Rule(
                id="laptops-color-from-title",
                layer=CATEGORY,
                why=(
                    "A colour the registry knows, whole in the title, where no field gave one:"
                    " `/Space Black/`, `| Arctic Grey |`, `Business Black`. Between the two"
                    " rules 1339 of bigbox's 2184 new laptops; most of the rest name none."
                ),
                body=devices.color_from_title,
            ),
            Rule(
                id="laptops-cpu",
                layer=CATEGORY,
                why=(
                    "`226V` and `228V` are two ThinkPads at two prices, and bigbox's field"
                    " says `Intel Core Ultra 5` for both. So the chip is read from the title"
                    " in every shape measured over 2184 of bigbox's new laptops on 24.09.2026"
                    " — `Core Ultra 5 226V`, `ULT7-355`, `U5 322`, `i5-13420H`, `Core 5-120U`,"
                    " `R7-260`, `Ryzen AI R7-350`, `AMD Ryzen 5 | 220` from a spec-sheet"
                    " title — and where the title gives only the number, `… IPS 150U 16 GB`,"
                    " the field's family completes it. 2000 of 2184 read one. A coarser name"
                    " gives way to a finer one, `Apple M5` to `Apple M5 Max`; two chips, or a"
                    " field naming another maker than the chip read — bigbox files two Intel"
                    " ThinkPads as `AMD Ryzen 7` — leave the axis empty."
                ),
                body=_cpu,
            ),
            Rule(
                id="laptops-gpu",
                layer=CATEGORY,
                why=(
                    "A discrete card by its model, `integrated` where a source says the"
                    " processor's own — a field naming Intel or Radeon and no card, a title's"
                    " `Intel Graphics`, `Radeon 610M`, `Adreno` or Lenovo's `/INT/` slot, or a"
                    " chip that has no discrete graphics beside it at all, Apple's and"
                    " Qualcomm's. 2127 of 2184. `RTX 500 Ada` and `RTX PRO 500` are two"
                    " generations and stay two; a field's `RTX 5070` gives way to the title's"
                    " `RTX 5070 Ti`."
                ),
                body=_gpu,
            ),
            Rule(
                id="laptops-keyboard",
                layer=CATEGORY,
                why=(
                    "An English and a Nordic ThinkPad are two part numbers — `21X0000LMH` and"
                    " `21X0000LMX` — and a buyer wants the one they can type on. A field the"
                    " registry knows, or the word a title puts in front of `kbd`, `Kb` or"
                    " `keyboard`: `Pro/Nordic Backlit kbd`, `BT/US Kb`. The marker is what makes"
                    " a bare `ENG` a keyboard; Lenovo's `/INT/` is its graphics. The words"
                    " themselves are the registry's. Most shops state no layout, and those"
                    " listings are left without the axis."
                ),
                body=_keyboard,
            ),
            Rule(
                id="laptops-ram",
                layer=CATEGORY,
                why=(
                    "Not the phone rule: a laptop's title names several sizes, and `32GB"
                    " SSD1TB` puts the memory first. A size is memory where it is marked so"
                    " — `16GB RAM`, `32GB LPDDR5X`, `RAM 16GB` — or is the first of a pair,"
                    " `16GB/512GB`, which every shop writes memory first, or stands directly"
                    " in front of the storage, `16GB/512SSD`. Field and title must agree."
                    " 2156 of 2184."
                ),
                body=_ram,
            ),
            Rule(
                id="laptops-screen",
                layer=CATEGORY,
                why=(
                    "To a tenth of an inch, because 15.6 and 16 are two laptops. A maker"
                    " names a screen by the whole inch below it — Apple's `MacBook Air 13\"`"
                    " is 13.6 in bigbox's field — so a whole number and a size within that"
                    " inch are one screen and the exact one is kept; the 13-inch MacBook Airs"
                    " all read nothing until that was so. 2140 of 2184."
                ),
                body=_screen,
            ),
            Rule(
                id="laptops-storage",
                layer=CATEGORY,
                why=(
                    "A size marked as storage — `512GB SSD`, `SSD1TB`, `SSD512`, `1TB NVMe` —"
                    " or the second of a pair, `16GB/512GB`; one distributor writes `1 SSD`"
                    " for a terabyte. Field and title must agree. 2143 of 2184."
                ),
                body=_storage,
            ),
            Rule(
                id="laptops-model-cut-from-title",
                layer=FINISH,
                why=(
                    "The name in front of the configuration: the words for the kind of thing"
                    " and the maker off the front, the title cut at the first processor, size,"
                    " panel word or separator, and a maker's configuration code taken out"
                    " wherever it stands — `21QG006FMH`, `X1504VA-BQ4296W` — because some shops"
                    " write it into the name and others do not. `Ultra` is a processor only"
                    " with its tier: `OmniBook Ultra Flip` is a name. Over bigbox's 2184 new"
                    " laptops, 743 names and 41 titles that gave none."
                ),
                body=_model_from_title,
            ),
            Rule(
                id="laptops-model-does-not-repeat-the-maker",
                layer=FINISH,
                why="As for a phone: the title composes brand and model, so a model holds none.",
                body=devices.without_the_maker,
            ),
            Rule(
                id="laptops-model-without-a-trailing-colour",
                layer=FINISH,
                why=(
                    "A colour is an axis, and a model that ends in one files each colour as a"
                    " product of its own: dateks's `Modelis` reads `ThinkPad P16 Gen 3 Black`"
                    " and `Pro 16 Platinum Silver` on 52 of its 709 laptops. Only a colour the"
                    " registry knows, only off the end, and never the whole model."
                ),
                body=_without_a_trailing_colour,
            ),
            Rule(
                id="laptops-model-from-the-registry",
                layer=FINISH,
                why=(
                    "Dell's 2025 names put the size before the tier — `Dell Pro 14 Essential`,"
                    " `Dell 16 Plus`, `Alienware 16 Aurora` — and the shops write them in either"
                    " order: on 25.09.2026 `Pro Essential 14` 17 times beside `Pro 14 Essential`"
                    " 78, `Plus 16` 7 beside `16 Plus` 5, `Alienware Aurora 16` 4 beside"
                    " `Alienware 16 Aurora` 4, and dateks in capitals — `PRO 14 PLUS 2IN1`. No"
                    " cut of the title turns one order into the other; each spelling became a"
                    " family of its own, 63 of them for Dell."
                    "\n\n"
                    "Which spelling is the maker's is a fact about Dell, so it is rows in"
                    " `model_aliases` and this is only the matching phones already use: the"
                    " longest known name found whole in the title, else in the model the rules"
                    " before this cut, and nothing replaced when none is found. A maker with no"
                    " page of laptop names is left as its shop read it."
                ),
                body=devices.from_the_registry,
            ),
            Rule(
                id="laptops-glass",
                layer=FINISH,
                why=(
                    "A MacBook Pro comes with standard glass or nano-texture glass, at two"
                    " prices; it was on the model, `MacBook Pro Nano-texture`, a family of"
                    " its own with 95 listings on 25.09.2026. It is an axis, as for a"
                    " tablet: nano-texture where the title says so, standard everywhere else."
                ),
                body=glass.the_glass,
            ),
        ),
    ),
)
