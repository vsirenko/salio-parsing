"""What a phone listing means, whichever shop it came from.

Written against 520 real phones collected on 21.09.2026. Everything here is about the kind
of product rather than about a shop: where a shop hides its storage figure is a source
rule, but that storage is what tells two otherwise identical phones apart is true of every
shop that sells them.
"""

from app.features.offers.normalization import devices, edition
from app.features.offers.normalization.rules import (
    CATEGORY,
    FINISH,
    Rule,
    Ruleset,
    register,
)

SLUG = "phones"
# Bumped when a rule body changes, not only when a rule is added: the version is
# what a reparse compares to decide whether a stored reading is stale, so a fix
# that leaves it alone is a fix that never reaches the rows it was written for.
VERSION = "phones-18"

RULESET = register(
    CATEGORY,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="phones-storage",
                layer=CATEGORY,
                why=(
                    "Capacity is what tells two otherwise identical phones apart, and it is"
                    " written in two places and three units: an attribute on 98.5% of these"
                    " products and the title on 96.9%, as GB on 429, TB on 26 and MB on 49."
                    " Megabytes rather than gigabytes because everything converts to them"
                    " exactly: a feature phone with 32 MB would otherwise be 0.03125 GB, and"
                    " an identity axis that is a fraction is an identity axis that will"
                    " eventually be compared wrongly. Two traps, both met on real data:"
                    " a shop writes the unit into the attribute name (`Iekšējā atmiņa, GB`)"
                    " so names match as fragments, and working memory is named the same way"
                    " by both shops, so anything mentioning RAM is refused outright. In a"
                    " title the largest size wins, whichever order a shop writes the pair"
                    " in: one writes `12GB/512GB`, RAM first, and another `128/4 GB`,"
                    " capacity first with a single unit at the end. Taking the first read"
                    " a phone as having half a gigabyte; reading only the half that"
                    " carries a unit read another as having four."
                ),
                body=devices.storage,
            ),
            Rule(
                id="phones-color",
                layer=CATEGORY,
                why=(
                    "The other axis that splits a phone into variants, and the one that"
                    " stayed unwritten longest. Cut out of a title the word takes 358 forms"
                    " across one shop's 1153 titled products, and they are three problems"
                    " wearing one shape: Latvian declension, plain language, and the maker's"
                    " own marketing — `Obsidian`, `Glacier`, `Cosmic Orange`. Only the first"
                    " is a category's business, and canonicalising the third by guessing"
                    " splits one product into several with confidence."
                    "\n\n"
                    "What unblocked it was a shop that states colour in a field rather than"
                    " leaving it in a title: 99.9% of its 1396 phones, in 37 forms rather"
                    " than 358, already reduced to real colours by whoever runs the shop."
                    " So this reads a field and never a title, and resolves it through the"
                    " registry the caller loaded — 37 canonical values with their Latvian"
                    " and plain-English spellings. The marketing names are deliberately not"
                    " in it: the pairs that could be learned from that one shop include"
                    " `evening blue` meaning grey and `desert titanium` meaning gold, which"
                    " is the confident wrong answer this rule existed to avoid."
                    "\n\n"
                    "The lookup was exact for as long as every shop that stated a colour"
                    " stated one word. Two of them state a phrase — `light blue`,"
                    " `tumši zils` — and got nothing at all: 104 products between dateks and"
                    " euronics. It resolves through `colours` now, which reads a phrase by"
                    " dropping words off the front, and that brings 93 of them in. The other"
                    " 11 are a field naming two or three colours at once, and they are"
                    " refused rather than reduced: dropping words off the front reads"
                    " `black, orange` as `orange`, which is not a partial answer but a wrong"
                    " one. A separated field is resolved as a pair or not at all."
                ),
                body=devices.color,
            ),
            Rule(
                id="phones-color-from-title",
                layer=CATEGORY,
                why=(
                    "The rule above reads a field and never a title, and that stands: cut"
                    " from a title the word takes 358 forms across one shop's products, and"
                    " canonicalising those by guessing splits one product into several."
                    " This is not that. It asks whether the title contains a word the"
                    " registry has **already been given an answer for** — which is a lookup,"
                    " not a guess — and a word nobody entered produces nothing."
                    "\n\n"
                    "Measured before it was written. Where a shop states a colour in a field"
                    " as well, the title word agrees on 4988 readings and disagrees on 320,"
                    " and the disagreements are granularity rather than contradiction:"
                    " burgundy against red, mint against green, navy against blue, graphite"
                    " against grey. Checked again on m79.lv alone, which states a field on"
                    " 15% of its cards: 222 agree, 18 disagree, and 11 of those 18 are a"
                    " two-tone field the title wrote as one colour. None of it fires in"
                    " practice, because this only runs where the field gave nothing."
                    "\n\n"
                    "What it is worth: 1547 of m79's 2390 colourless listings get a colour,"
                    " almost all of them a plain word a shop wrote in its own title —"
                    " `black` 426, `blue` 209, `white` 110, `orange` 91, `silver` 85. Those"
                    " listings carry no barcode either, and colour is the axis that was"
                    " keeping them from becoming a catalogue entry."
                    "\n\n"
                    "Words side by side are one phrase, not two colours. `Titanium Silver`,"
                    " `Midnight Blue` and `Glacier Blue` all carry two entries the registry"
                    " knows, and counting distinct values refused every one of them: 130"
                    " listings, of which 99 are a single phrase and only 31 name two"
                    " colours. A run is broken by anything but a space, because a shop"
                    " writing `Black/Orange` means both — and joining those is how"
                    " `black/orange` becomes `orange`, which is not a partial answer but a"
                    " wrong one."
                    "\n\n"
                    "One known cost. A maker's palette lives in the brand layer, which runs"
                    " after this, and a palette only fills a colour that is missing — so on"
                    " a title carrying both a registry word and a maker's name for the same"
                    " colour, the coarser answer wins: `Titanium Jadegreen` reads as"
                    " `titanium` rather than green. Nineteen listings in the corpus, all"
                    " Samsung's `Titanium` line, and `titanium` is a material the registry"
                    " calls a colour — which is the thing to fix, rather than this."
                ),
                body=devices.color_from_title,
            ),
            Rule(
                id="phones-model-does-not-repeat-the-maker",
                layer=FINISH,
                why=(
                    "`Motorola Motorola G06 Power` is how a catalogue entry came out, and"
                    " 301 of 2939 of them read that way: the title composes the brand and"
                    " the model, and the model already held the brand. It gets there because"
                    " a shop that states no maker in a field leaves it at the front of the"
                    " name, and the shop's own rule can only cut off a brand the shop"
                    " stated. 1821 of m79's 2680 models repeat the maker, and euronics,"
                    " discover, bm, rdveikals and dateks all do it too."
                    "\n\n"
                    "Which word is the maker is not something a rule can know and not"
                    " something the shop says, so the names are handed in as vocabulary —"
                    " the same way the words for `phone` are. A catalogue with no brands in"
                    " it yet hands in nothing and this does nothing, which is the right"
                    " behaviour rather than a gap."
                    "\n\n"
                    "Last of all, because the model is what every layer before this one"
                    " worked out. Through `naming.without_brand` so the cut respects a word"
                    " boundary: `CAT` against `Caterpillar CAT S75` once cut mid-word."
                ),
                body=devices.without_the_maker,
            ),
            Rule(
                id="phones-model-without-a-trailing-colour",
                layer=FINISH,
                why=(
                    "`Cat S31 Black`, `Nokia 106 Black`, `Galaxy S10 Lite Grey`: a title with no"
                    " capacity in it gives a shop's subtraction nothing to cut at, and the"
                    " colour stays on the model — one catalogue entry per colour, named after"
                    " one of them. Five listings on 22.09.2026, four at bm and one at"
                    " rdveikals, and the colour itself had already been read correctly off the"
                    " same title. m79 does this in its own rules; it belongs to every shop."
                    "\n\n"
                    "The words are the registry's colours, handed in, so no shop's or"
                    " language's words live here. Only off the end and never the last word:"
                    " a colour in the middle of a name is part of the name."
                ),
                body=devices.without_a_trailing_colour,
            ),
            Rule(
                id="phones-model-from-the-registry",
                layer=FINISH,
                why=(
                    "211 of 1524 catalogue entries were named `Galaxy S26 S942 5G Dual Sim`,"
                    " `razr fold 20.6 cm Dual SIM Android 16.0` and the like, 170 of them by"
                    " the two shops that publish no model field. Their rules cut the model"
                    " out of the title by subtraction — everything before the first capacity"
                    " — and subtraction cannot be made clean, because the list of what to cut"
                    " is open: `5G`, `Dual Sim`, `Hybrid Dual SIM`, `USB Type-C`, `17.3 cm`,"
                    " an internal code, a German `Interner Speicher`. Every rule closes one"
                    " tail and the next shop opens another."
                    "\n\n"
                    "Recognition is closed: a title holds a name the registry knows or it"
                    " does not. Measured against the 845 spellings the eight clean shops"
                    " read, a known name sits whole in 77% of bm's titles and 88% of m79's,"
                    " where the model those shops' own rules read agrees with the rest of"
                    " the market on 21% and 26%. The name was there all along."
                    "\n\n"
                    "Which words are a model is the same kind of fact as which words are a"
                    " colour, so it is rows — `model_aliases`, per maker — handed in as"
                    " vocabulary, and this holds only the matching: whole words, longest"
                    " wins, two different names decide nothing. The registry cannot be"
                    " derived from the catalogue it is meant to clean: `Galaxy S26 S942 5G"
                    " Dual Sim` is in the title too, and as the longest known name it would"
                    " win. It is seeded from the shops that read cleanly and grown by hand."
                    "\n\n"
                    "A title holding no known name keeps what the shop's rule cut out. The"
                    " tail is a shop selling what nobody else sells — Nubia, Blackview,"
                    " ZTE — and a spelling the registry has not been told: `Samsung S26`"
                    " without its `Galaxy`. Both are rows, not rules."
                ),
                body=devices.from_the_registry,
            ),
            Rule(
                id="phones-model-without-the-edition",
                layer=FINISH,
                why=(
                    "Samsung sells most of its phones a second time as an Enterprise Edition —"
                    " the same phone under barcodes and part numbers of its own, at its own"
                    " price: 1459 € against 1039 € for an S26 Ultra 256 at 1a.lv and Ksenukai"
                    " on 26.09.2026. On the model — `Galaxy S26 Ultra 5G EE`, `… Enterprise"
                    " Edition` — it was a family of its own, and where only the part number or"
                    " the barcode said it the reading was the ordinary model and a rebuild"
                    " merged the two entries. Measured that day over every Samsung listing: a"
                    " part number ending `EE…` (`EEE`, `EEB`, `EEA`) shared its barcode with a"
                    " listing that says Enterprise 12 times in 12 and with an ordinary"
                    " `EUE`/`EUB` one never; bigbox's and m79's bare `EE` 4 in 4 and never."
                    " So it is an axis: enterprise where the words, the abbreviation or the"
                    " part number say so, standard everywhere else, and the words leave the"
                    " model. After the registry, which spells `… 5G EE` names of its own."
                    "\n\n"
                    "Samsung's only, asked of the listing: `EE` is an Estonian keyboard in"
                    " Dell's and Asus's laptop titles, and the one other phone saying"
                    " Enterprise that day was a DECT handset, `Enterprise 8254`."
                ),
                body=edition.the_edition,
            ),
        ),
    ),
)
