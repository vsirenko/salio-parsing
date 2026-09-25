"""Reading a laptop: the configuration, axis by axis, and the name in front of it.

Every title here is one of bigbox's, collected on 24.09.2026.
"""

import pytest

from app.features.attributes.normalization import normalize_attribute_name
from app.features.offers.normalization import read
from app.features.offers.normalization.rules import Vocabulary

FIELDS = {
    "Operatīvā atmiņa, (RAM)": "ram_mb",
    "Cietā diska ietilpība": "storage_mb",
    'Ekrāna diagonāle, "': "screen_inch",
    "Datora procesora tips": "cpu",
    "Videokarte": "gpu",
}
VOCABULARY = Vocabulary(
    category_names=frozenset({"portatīvais", "dators", "klēpjdators"}),
    brand_names=frozenset({"lenovo", "dell", "hp", "asus", "apple", "msi"}),
    attribute_names={normalize_attribute_name(k): v for k, v in FIELDS.items()},
    values={
        "keyboard_layout": {
            "eng": "english",
            "en": "english",
            "us": "english",
            "nordic": "nordic",
            "nor": "nordic",
            "swe": "swedish",
            "vācu": "german",
        }
    },
)


def laptop(title: str, brand: str = "Lenovo", **attributes: str) -> dict:
    return read(
        {"title": title, "brand": brand, "attributes": attributes},
        source_slug="bigbox-laptops",
        shop_slug="bigbox",
        category="laptops",
        vocabulary=VOCABULARY,
    )


def axis(title: str, key: str, brand: str = "Lenovo", **attributes: str):
    return laptop(title, brand, **attributes)["identity"].get(key)


# --- the processor ---


@pytest.mark.parametrize(
    ("title", "chip"),
    [
        (
            'Lenovo ThinkPad E14 Gen 7, 14" WUXGA, Core Ultra 5 226V, 16 GB',
            "Intel Core Ultra 5 226V",
        ),
        ("Lenovo ThinkPad L16 Gen 3 16 WUXGA ULT7-355/24GB/512GB", "Intel Core Ultra 7 355"),
        # Lunar Lake: every one ends in V, which shops space off or drop.
        ("Lenovo Yoga Slim 7 Ultra 7 258 32GB 1TB", "Intel Core Ultra 7 258V"),
        ("HP OmniBook Ultra Flip 14 Ultra 5 226 V 16 GB 512 SSD", "Intel Core Ultra 5 226V"),
        ("HP PB 4 G2i U5 322 16i 16/512 GB", "Intel Core Ultra 5 322"),
        ("ASUS TUF Gaming 16 FX610 i5-14450HX / 16 GB / 512 GB", "Intel Core i5-14450HX"),
        ("ASUS ExpertBook P1503CVA-S72255W - Core 5-210H | 15,6''", "Intel Core 5 210H"),
        ('Acer Nitro V16 Gaming 16" WUXGA, Ryzen R7-260 (16 TOPS), 16GB RAM', "AMD Ryzen 7 260"),
        ('Acer Nitro V14 AI 14,5" WUXGA, Ryzen AI R7-350 (50 TOPS)', "AMD Ryzen 7 350"),
        ("Lenovo ThinkPad P14s Gen 7 14 WUXGA AMD R5 AI PRO 440/16GB/512GB", "AMD Ryzen 5 440"),
        ("Dell Inspiron 14 5445 AG FHD+ AR5-8540U/16GB/1TB", "AMD Ryzen 5 8540U"),
        ("Lenovo Legion Pro 7 16AFR10H | AMD Ryzen 9 | 9955HX3D | 64 GB", "AMD Ryzen 9 9955HX3D"),
        (
            "ASUS ROG Flow Z13 GZ302EA-RU137X - Ryzen AI MAX+ 395 | 13,4 collu",
            "AMD Ryzen AI Max+ 395",
        ),
        (
            'ASUS ZenBook A14 OLED UX3407QA-QD289W - Snapdragon X1-26-100 | 14"',
            "Qualcomm Snapdragon X1-26-100",
        ),
        (
            'Klēpjdators Apple MacBook Neo 13" Apple A18 Pro 6C CPU, 5C GPU/8GB/256GB SSD',
            "Apple A18 Pro",
        ),
    ],
)
def test_the_chip_in_every_shape_a_shop_writes(title, chip):
    assert axis(title, "cpu") == chip


def test_a_bare_number_is_completed_by_the_field_s_family():
    """`… IPS 150U 16 GB …`: the title has the number, the field the family."""
    title = "16 DC16251 16 FHD+ IPS 150U 16 GB 1 SSD MX570A EN W11P Sudraba"
    fields = {"Datora procesora tips": "Intel Core 7 / i7"}
    assert axis(title, "cpu", "Dell", **fields) == "Intel Core 7 150U"
    # A storage size beside it is not a candidate.
    title = "EliteBook 6 G1i 16 WUXGA 225U 16 GB 512 SSD EN W11P"
    assert axis(title, "cpu", "HP", **{"Datora procesora tips": "Intel Core Ultra 5"}) == (
        "Intel Core Ultra 5 225U"
    )


def test_a_coarser_name_gives_way_and_another_maker_does_not():
    title = 'Klēpjdators Apple MacBook Pro 14" Apple M5 Max 18C CPU, 32C GPU, 36GB/2TB SSD'
    assert axis(title, "cpu", "Apple", **{"Datora procesora tips": "Apple M5"}) == "Apple M5 Max"
    # bigbox files two Intel ThinkPads as AMD: the two disagree, and neither is taken.
    title = "Lenovo ThinkPad X13 Gen 7 Touch 13.3 WUXGA ULT7-355/32GB/512GB/Intel Graphics"
    assert axis(title, "cpu", **{"Datora procesora tips": "AMD Ryzen 7"}) is None


def test_a_chip_is_named_as_intel_names_it_whatever_the_shop_wrote():
    """An Ultra's number ends in 5, 6 or 8 and a plain Core's in 0; shops write one for the
    other, and AMD's `PRO` is kept by one shop and dropped by the next."""
    assert axis("Acer TravelMate TMP215-55 Intel Core 5 225U/16GB/512GB", "cpu", "Acer") == (
        "Intel Core Ultra 5 225U"
    )
    assert axis("ASUS Vivobook 15 - Core Ultra 5 120U | 15,6", "cpu", "Asus") == "Intel Core 5 120U"
    assert (
        axis(
            "ThinkPad X13 G6 21RM003NPB W11Pro 7 PRO 350/32GB/1TB",
            "cpu",
            **{"Datora procesora tips": "AMD Ryzen 7"},
        )
        == "AMD Ryzen 7 350"
    )
    # `256 GB` after the tier is the drive, not a chip.
    assert axis("ASUS Vivobook 14 Flip OLED TP3407SA-SG142W - Ultra 7 - 256 GB", "cpu", "Asus") != (
        "Intel Core Ultra 7 256GB"
    )


def test_a_maker_s_code_is_not_a_chip():
    """`GU605CW-U9322W` has a `U9 322W` inside it."""
    title = 'ASUS ROG Zephyrus G16 GU605CW-U9322W Ultra 9 285H 16"2.5K OLED 240Hz 32GB'
    assert axis(title, "cpu", "Asus") == "Intel Core Ultra 9 285H"


# --- memory, storage, screen ---


def test_memory_and_storage_are_told_apart():
    """`32GB SSD1TB` puts the memory first; the phone rule took the larger as storage and
    had no memory at all."""
    fields = laptop('Dell 16-Plus-9052BLU Ultra 9 288V 16" WUXGA Touch 32GB SSD1TB BT', "Dell")
    assert (fields["identity"]["ram_mb"], fields["identity"]["storage_mb"]) == (32768, 1048576)
    pair = laptop("LENOVO V15 G4 R7-7730U/15.6FHD/16GB/512SSD/W11HOME/1Y/ENG")["identity"]
    assert (pair["ram_mb"], pair["storage_mb"]) == (16384, 524288)


def test_a_field_and_a_title_that_disagree_leave_the_axis_empty():
    title = "Lenovo IdeaPad Slim 3 15AMN8 16GB LPDDR5-5500 SSD512 Radeon 610M"
    assert axis(title, "ram_mb", **{"Operatīvā atmiņa, (RAM)": "8 GB"}) is None


def test_the_screen_is_kept_to_a_tenth_and_a_whole_inch_names_the_one_within_it():
    assert (
        axis('MSI Cyborg 15 A13VE-1005, 39,62 cm (15,6"), 144 Hz, i5-13420H', "screen_inch", "MSI")
        == 15.6
    )
    # Apple's `13"` MacBook Air is 13.6 in the field.
    title = "Klēpjdators Apple MacBook Air 13” Apple M5 10 CPU, 8C GPU/16GB/512GB SSD"
    assert axis(title, "screen_inch", "Apple", **{'Ekrāna diagonāle, "': "13.6"}) == 13.6


# --- graphics ---


def test_a_card_by_its_model_and_the_processor_s_graphics_as_one_word():
    assert axis("Lenovo LOQ 15AHP10 Ryzen 7 250 / 16 GB / 512 GB / RTX 5050", "gpu") == (
        "NVIDIA GeForce RTX 5050"
    )
    title = "Acer Nitro 16 AI - Ryzen AI 9 365 | 16 collu | 32 GB | 1 TB | RTX 5070 Ti"
    assert axis(title, "gpu", "Acer", Videokarte="NVIDIA GeForce RTX 5070") == (
        "NVIDIA GeForce RTX 5070 Ti"
    )
    assert (
        axis("ThinkPad L14 G6 21S6008HPB Ultra 5 225U/16GB/512GB/INT/14.0", "gpu") == "integrated"
    )
    assert axis("ThinkPad T14 G6 14 FHD+ IPS 225U 16 GB", "gpu", Videokarte="Intel") == "integrated"
    # Snapdragon has no discrete graphics beside it at all.
    title = 'HP OmniBook 5 16-fb0135dx, 16" WUXGA, Snapdragon X Plus X1P-42-100, 16 GB RAM'
    assert axis(title, "gpu", "HP", Videokarte="Citi") == "integrated"


def test_the_two_workstation_generations_stay_two():
    assert axis("ZBook Ultra G1a 14 WUXGA 390 32 GB 1 SSD RTX 500 Ada EN W11P", "gpu", "HP") == (
        "NVIDIA RTX 500 Ada"
    )
    assert axis(
        "Dell Pro Precision 5 16 PW516261 AG FHD+ Ultra 7 366H/32GB/512GB"
        "/NVIDIA RTX PRO 500 Blackwell",
        "gpu",
        "Dell",
    ) == ("NVIDIA RTX PRO 500")


# --- the keyboard ---


def test_a_layout_is_a_word_in_front_of_kbd_or_the_code_before_the_system():
    title = (
        "Lenovo ThinkPad P14s Gen 7 14 WUXGA AMD R5 AI PRO 440/16GB/512GB/WIN11Pro"
        "/Nordic Backlit kbd/FP"
    )
    assert axis(title, "keyboard_layout") == "nordic"
    assert axis(
        "ThinkPad T14 G6 14 FHD+ IPS 225U 16 GB 256 SSD EN W11Pr Black", "keyboard_layout"
    ) == ("english")
    # bigbox's unnamed field.
    assert (
        axis("Lenovo ThinkPad T14 G6", "keyboard_layout", attribute_string_1171="vācu") == "german"
    )
    # Lenovo's `/INT/` is graphics, not an international keyboard.
    assert (
        axis("ThinkPad L14 G6 21S6008HPB Ultra 5 225U/16GB/512GB/INT/14.0", "keyboard_layout")
        is None
    )


def test_a_macbook_s_part_number_names_its_keyboard():
    title = (
        "Klēpjdators Apple MacBook Air 13” Apple M5 10 CPU, 8C GPU/16GB/512GB SSD/Silver/SWE"
        " MDH74KS/A"
    )
    assert axis(title, "keyboard_layout", "Apple") == "swedish"
    assert axis(
        title.replace("KS/A", "ZE/A").replace("SWE", "Silver"), "keyboard_layout", "Apple"
    ) == ("english")


# --- the name ---


@pytest.mark.parametrize(
    ("title", "brand", "model"),
    [
        ('Lenovo ThinkPad T16 G5 AMD | Black | 16 " | IPS | WUXGA', "Lenovo", "ThinkPad T16 G5"),
        (
            'Portatīvais dators Lenovo IdeaPad Slim 3 16IAH8 16", Intel Core i5-12450H',
            "Lenovo",
            "IdeaPad Slim 3",
        ),
        ("HP OmniBook Ultra Flip 14-fh0172ng, t.sk. HDMI adapteris", "HP", "OmniBook Ultra Flip"),
        ("ASUS VivoBook 15 X1504VA-BQ4296W - Core i7-150U | 15,6 collu", "Asus", "VivoBook 15"),
        ("Dell Pro 16 AG FHD+ AMD Ryzen AI 7 350/16GB/512GB", "Dell", "Pro 16"),
        ("Pro 14 14 FHD+ IPS 350 32 GB 1 SSD EN W11Pro", "Dell", "Pro 14"),
        ("„Dell Pro Max 16 Plus“ MB16250 Ultra 9 285HX", "Dell", "Pro Max 16 Plus"),
        (
            "Klēpjdators Apple MacBook Air 15” Apple M5 10C CPU, 10C GPU/16GB/1TB SSD",
            "Apple",
            "MacBook Air",
        ),
        # rdveikals names the screen bare, with no unit and no separator.
        (
            "portatīvais dators Dell Pro 15 Essential PV15250 15.6 FHD i7-1355U 16GB 1SSD EN",
            "Dell",
            "Pro 15 Essential",
        ),
        (
            "portatīvais dators Dell 16 Plus 16 120hz 256V 16GB 512SSD EN W11Pro Ice Blue",
            "Dell",
            "16 Plus",
        ),
        (
            "portatīvais dators Asus TUF Gaming A14 FA401EA-RG005W 14 165hz 392 64GB 1SSD EN",
            "Asus",
            "TUF Gaming A14",
        ),
        ("portatīvais dators MSI Thin 15 B12UC-2049NL 15.6 144Hz i7-12650H 16GB", "MSI", "Thin 15"),
        (
            "portatīvais dators Asus ROG Strix G18 G815LR-U9R321X 300hz U9-290HX 32GB",
            "Asus",
            "ROG Strix G18",
        ),
        # bigbox opens some names with a straight quote, and leaves underscores in front.
        ('"Dell Pro 14 - Ultra 5 235U | 14 collu | 16 GB | 512 GB | Win11Pro', "Dell", "Pro 14"),
        ('"Dell Pro 14 Essential" PV14250 | 14 collu | 16 GB', "Dell", "Pro 14 Essential"),
        ("___Pro 14 Plus 14 FHD+ 16 GB", "Dell", "Pro 14 Plus"),
        # A whole inch that is the name stays.
        ("Dell XPS 16 - Ultra 7 155H | 16 collu | 32 GB", "Dell", "XPS 16"),
        ("Dell Latitude 5420 14 FHD i5-1145G7 16GB 256GB", "Dell", "Latitude 5420"),
        ("Dell Pro Precision 5 14 - Ultra 7 265H | 14 collu | 32 GB", "Dell", "Pro Precision 5 14"),
        ("portatīvais dators Dell Inspiron 14 Plus 14FHD+ 7640 16GB", "Dell", "Inspiron 14 Plus"),
        ('"Dell 15 DC15250" - Core 3 100U | 15,6 collu | 8 GB', "Dell", "15"),
    ],
)
def test_the_name_is_what_stands_in_front_of_the_configuration(title, brand, model):
    assert laptop(title, brand)["model"] == model


@pytest.mark.parametrize(
    ("stated", "model"),
    [
        ("ThinkPad P16 Gen 3 Black", "ThinkPad P16 Gen 3"),
        ("Pro 16 Platinum Silver", "Pro 16"),
        ("16 Plus Ice Blue", "16 Plus"),
        ("Pro 16 Magnetite", "Pro 16 Magnetite"),
        ("Black", "Black"),
    ],
)
def test_a_colour_comes_off_the_end_of_a_model_however_it_was_found(stated, model):
    """dateks's `Modelis` carries the colour; only what the registry knows comes off."""
    colours = {"black": "black", "silver": "silver", "platinum": "silver", "ice blue": "blue"}
    vocabulary = Vocabulary(
        category_names=VOCABULARY.category_names,
        brand_names=VOCABULARY.brand_names,
        colours=colours,
    )
    reading = read(
        {"title": f"Dell {stated}, 16 collu", "brand": "Dell", "model": stated},
        source_slug="dateks-laptops",
        shop_slug="dateks",
        category="laptops",
        vocabulary=vocabulary,
    )
    assert reading["model"] == model


DELL = {
    "dell": {
        "pro 14 essential": "Pro 14 Essential",
        "pro essential 14": "Pro 14 Essential",
        "pro 14": "Pro 14",
        "pro 14 plus": "Pro 14 Plus",
        "pro 14 plus 2in1": "Pro 14 Plus 2-in-1",
        "14 plus": "14 Plus",
        "plus 14": "14 Plus",
        "14 plus 2 in 1": "14 Plus 2-in-1",
        "plus 14 2 in 1": "14 Plus 2-in-1",
    }
}


@pytest.mark.parametrize(
    ("title", "model"),
    [
        ('"Dell Pro Essential 14 AG FHD+ ar AMD Ryzen 5 220 procesoru', "Pro 14 Essential"),
        ('"Dell Pro 14 Essential" - Ryzen 7 250 | 14 collu | 16 GB', "Pro 14 Essential"),
        ("Dell DELL PRO 14 PLUS 2IN1 U5-235U/14FHT+/16GB/512SSD", "Pro 14 Plus 2-in-1"),
        ('Dell Pro 14 PC14250 Platiunum Silver, 14" WUXGA', "Pro 14"),
        ('Dell Plus 14 2-in-1 DB04250 | Ice Blue | 14 "', "14 Plus 2-in-1"),
        ("portatīvais dators Dell Plus 14 FHD+ 340 16GB 1SSD EN W11P", "14 Plus"),
        # A name the registry does not hold keeps the shop's reading.
        ("Dell Latitude 5430 14.0-inch FHD i5-1235U 8GB", "Latitude 5430"),
    ],
)
def test_a_laptop_is_named_as_the_registry_spells_it(title, model):
    reading = read(
        {"title": title, "brand": "Dell"},
        source_slug="rdveikals-laptops",
        shop_slug="rdveikals",
        category="laptops",
        vocabulary=Vocabulary(
            category_names=VOCABULARY.category_names,
            brand_names=VOCABULARY.brand_names,
            models=DELL,
        ),
    )
    assert reading["model"] == model


# --- the channel ---


def test_the_laptop_channel_leaves_second_hand_stock_out():
    """All 282 of bigbox's `Rūpnīcā atjaunoti datori` said so in the title or the field."""
    from app.features.runs.channel import CHANNELS
    from app.features.runs.channels.bigbox import LAPTOPS_SLUG

    channel = CHANNELS[LAPTOPS_SLUG]
    assert channel.leaves_out('14" ThinkPad L14 G2 i5-1135G7 16GB 1TB SSD Windows 11 Pro ReNew', {})
    assert channel.leaves_out("HP PB 4 G1I 16 RENEW GOLD (B)", {})
    assert channel.leaves_out("Dell Latitude 5440", {"Atjaunots": "Jā"})
    assert not channel.leaves_out('Lenovo ThinkPad T14 Gen 6, 14" WUXGA', {"Atjaunots": "Nē"})


# --- rdveikals ---


def rd_laptop(title: str, **specs: str) -> dict:
    vocabulary = Vocabulary(
        category_names=VOCABULARY.category_names,
        brand_names=VOCABULARY.brand_names,
        attribute_names={
            normalize_attribute_name("Tastatūra / Tastatūras valodas"): "keyboard_layout",
        },
        values={
            "keyboard_layout": {
                **VOCABULARY.values["keyboard_layout"],
                "rus": "russian",
                "est": "estonian",
            }
        },
    )
    return read(
        {"title": title, "brand": "Lenovo", "specs": specs},
        source_slug="rdveikals-laptops",
        shop_slug="rdveikals",
        category="laptops",
        vocabulary=vocabulary,
    )


def test_rd_states_the_chip_in_three_fields_that_name_nothing_alone():
    fields = {
        "Procesors / Procesora ražotājs": "AMD",
        "Procesors / Procesora sērija": "Ryzen AI 9 Pro",
        "Procesors / Procesora modelis": "Pro 375",
    }
    title = "portatīvais dators HP EliteBook X G1a 14 OLED 375 64GB 2SSD EN W11Pro Silver"
    assert rd_laptop(title, **fields)["identity"]["cpu"] == "AMD Ryzen 9 375"
    # The field and the title naming two chips leave the axis empty.
    fields = {
        "Procesors / Procesora ražotājs": "Intel",
        "Procesors / Procesora sērija": "Core i7",
        "Procesors / Procesora modelis": "i7-14650HX",
    }
    title = "portatīvais dators Acer Nitro V 15 ANV15-52-750T i7-13620H 16GB 512SSD"
    assert "cpu" not in rd_laptop(title, **fields)["identity"]


def test_an_asus_model_is_not_a_chip():
    """`UX5406SA` read as `Ultra X5 406SA`; `FA608UP-R7165W` as `Ryzen 7 165W`."""
    from app.features.offers.normalization.categories.laptops import processors

    assert processors("Asus ZenBook S14 UX5406SA-QJ502W 14 OLED 256V 16GB") == set()
    assert processors("Asus TUF Gaming A16 FA608UP-R7165W 16 165hz 260 16GB") == set()


def test_a_keyboard_printed_for_two_languages_is_a_layout_of_its_own():
    field = {"Tastatūra / Tastatūras valodas": "ENG / RUS (ar apgaismojumu)"}
    assert rd_laptop("portatīvais dators Lenovo IdeaPad 5", **field)["identity"][
        "keyboard_layout"
    ] == ("english+russian")
    field = {"Tastatūra / Tastatūras valodas": "ENG (ar apgaismojumu)"}
    assert rd_laptop("portatīvais dators Lenovo IdeaPad 5", **field)["identity"][
        "keyboard_layout"
    ] == ("english")


def test_rd_s_part_number_field_is_the_maker_s_code():
    field = "Modeļa sērija / Modeļa nosaukums"
    assert rd_laptop("portatīvais dators Apple MacBook Air", **{field: "MDVT4KS/ A"})["mpn"] == (
        "MDVT4KS/A"
    )
    assert not rd_laptop("portatīvais dators Dell Pro 14", **{field: "Nav informācijas"}).get("mpn")


# --- the other shops ---


def shop_laptop(record: dict, source: str, shop: str, vocabulary: Vocabulary = VOCABULARY) -> dict:
    return read(
        record, source_slug=source, shop_slug=shop, category="laptops", vocabulary=vocabulary
    )


def test_euronics_and_bm_state_the_chip_over_three_fields():
    euronics = {
        "name": "Lenovo ThinkPad E14 Gen 7, 14'', WUXGA, Ryzen 5, 16 GB, 512 GB, W11P, ENG, black",
        "brand": "Lenovo",
        "specs": {"processor producer": "AMD", "processor type": "Ryzen 5", "processor": "220"},
    }
    assert shop_laptop(euronics, "euronics-laptops", "euronics")["identity"]["cpu"] == (
        "AMD Ryzen 5 220"
    )
    bm = {
        "name": "Lenovo LOQ 15ARP9 15.6-inch FHD 24GB RAM 1TB SSD RTX 4070",
        "brand": "Lenovo",
        "attributes": {
            "bm_procesora_razotajs_213": "AMD",
            "bm_procesora_serija_165": "AMD Ryzen 7",
            "bm_procesora_modelis_2400": "7435HS",
        },
    }
    assert shop_laptop(bm, "bm-laptops", "bm")["identity"]["cpu"] == "AMD Ryzen 7 7435HS"


def test_dateks_storage_is_its_drives_not_its_phones_internal_memory():
    """`Atmiņa > Iekšējā atmiņa` is a phone's storage and a laptop's working memory."""
    vocabulary = Vocabulary(
        attribute_names={
            normalize_attribute_name("Atmiņa > Iekšējā atmiņa"): "storage_mb",
            normalize_attribute_name("SSD"): "storage_mb",
        }
    )
    record = {
        "title": 'Lenovo IdeaPad Slim 3 15AMN8 Arctic Grey, 15.6" FHD IPS, 16GB, 512GB SSD',
        "brand": "Lenovo",
        "specs": {"Atmiņa > Iekšējā atmiņa": "16 GB"},
        "parameters": {"SSD": "512 GB", "HDD": "Nav"},
    }
    fields = shop_laptop(record, "dateks-laptops", "dateks", vocabulary)
    assert fields["identity"]["storage_mb"] == 524288


def test_a_chip_is_known_by_its_number_where_the_registry_knows_it():
    """1a's index names no family: `…, 226V, 16 GB, …`. A number standing as an item of
    the title's list is looked up; a bare three digits elsewhere is a name."""
    vocabulary = Vocabulary(
        values={"cpu": {"226v": "Intel Core Ultra 5 226V", "250": "AMD Ryzen 7 250"}}
    )
    title = 'Portatīvais dators Lenovo ThinkPad T T14 G6, 226V, 16 GB, 512 GB, 14 "'
    assert shop_laptop({"title": title, "brand": "Lenovo"}, "onea-laptops", "onea", vocabulary)[
        "identity"
    ]["cpu"] == ("Intel Core Ultra 5 226V")
    name = {"title": "HP 250 G10 15.6 FHD 16GB 512GB", "brand": "HP"}
    assert "cpu" not in shop_laptop(name, "onea-laptops", "onea", vocabulary)["identity"]


def test_ksenukai_and_1a_leave_their_refurbished_laptops_out():
    from app.features.runs.channels.ksenukai import second_hand

    assert second_hand({"title": "Atjaunots portatīvais dators Dell Latitude 5400, atjaunots"})
    assert second_hand({"title": "Portatīvais dators Dell", "attributes": {"Atjaunots": "Jā"}})
    assert not second_hand({"title": "Portatīvais dators Dell", "attributes": {"Atjaunots": "Nē"}})


def test_a_macbook_is_named_by_its_family_and_its_glass_is_an_axis():
    """bm writes the size into the name with no inch mark; the glass is an axis."""
    for title, glass in [
        ("Apple MacBook Pro 16 Apple M4 Max 16C CPU, 40C GPU 48GB RAM 8TB SSD Silver", "standard"),
        ("Apple MacBook Pro 14 M5 10 CPU 10 GPU 16GB 1TB Silver INT MDE54", "standard"),
        (
            "Apple MacBook Pro 16 Nano-texture Apple M4 Max 16C CPU, 40C GPU 128GB RAM 1TB SSD",
            "nano-texture",
        ),
    ]:
        fields = shop_laptop({"name": title, "brand": "Apple"}, "bm-laptops", "bm")
        assert (fields["model"], fields["identity"]["glass"]) == ("MacBook Pro", glass)


# --- cec and discover: the MacBooks of two Apple sellers ---

MAC_WORDS = Vocabulary(
    category_names=VOCABULARY.category_names,
    brand_names=VOCABULARY.brand_names,
    attribute_names={
        **VOCABULARY.attribute_names,
        normalize_attribute_name("erply_language"): "keyboard_layout",
    },
    values={
        "keyboard_layout": {
            **VOCABULARY.values["keyboard_layout"],
            "int": "english",
            "usa": "english",
            "ru": "russian",
            "rus": "russian",
        }
    },
)


def cec_mac(name: str, family: str, category: str = "MacBook Air", **options: str) -> dict:
    return read(
        {"id": "Z1", "name": name, "model": family, "category": category, "attributes": options},
        source_slug="cec-laptops",
        shop_slug="cec",
        category="laptops",
        vocabulary=MAC_WORDS,
    )


def discover_mac(name: str, line: str = "") -> dict:
    return read(
        {"id": "1", "name": name, "brand": "Apple", "line": line},
        source_slug="discover-laptops",
        shop_slug="discover",
        category="laptops",
        vocabulary=MAC_WORDS,
    )


def test_a_cec_macbook_is_apple_s_and_named_by_its_family():
    fields = cec_mac(
        'MacBook Pro 14" Apple M5 Pro 15‑core CPU & 16‑core GPU 24GB/1TB Space Black RUS',
        'MacBook Pro 14" Apple M5 Pro',
        category="MacBook Pro",
        erply_language="RUS",
    )
    assert (fields["brand_raw"], fields["model"]) == ("Apple", "MacBook Pro")
    assert fields["identity"]["keyboard_layout"] == "russian"
    # The whole inch it is named by, read as the diagonal it has.
    assert fields["identity"]["screen_inch"] == 14.2


def test_a_cec_simple_product_names_its_keyboard_last():
    name = "MacBook Air 13” Apple M5 10C CPU, 8C GPU/16GB/512GB SSD/Silver/USA"
    fields = cec_mac(name, name)
    assert fields["model"] == "MacBook Air"
    assert fields["identity"]["keyboard_layout"] == "english"
    assert fields["identity"]["screen_inch"] == 13.6


def test_a_discover_macbook_carries_its_part_number_and_its_keyboard_twice():
    fields = discover_mac(
        "Apple MacBook Air 15 M5 15.3 16GB/1TB 10C EN ENG Sky Blue (MDVT4ZE/A)", "MDVT4ZE/A"
    )
    assert fields["mpn"] == "MDVT4ZE/A"
    assert fields["identity"]["keyboard_layout"] == "english"
    assert fields["identity"]["screen_inch"] == 15.3
    russian = discover_mac("Apple MacBook Air 13 M5 13.6 16GB/512GB RU RUS Midnight")
    assert russian["identity"]["keyboard_layout"] == "russian"
    assert russian["identity"]["screen_inch"] == 13.6
    # The stem on an older one names no configuration.
    old = discover_mac("Apple MacBook Pro (2023) 14.2 M3 8C 8GB/1TB Retina Silver (MR7K3)", "MR7K3")
    assert old.get("mpn") is None
    assert old["identity"]["screen_inch"] == 14.2


@pytest.mark.parametrize(
    ("title", "screen"),
    [
        ('Apple MacBook Air 13" M1 8GB/256GB Space Gray', 13.3),
        ('Apple MacBook Air 13" M4 16GB/512GB Sky Blue', 13.6),
        ('Apple MacBook Pro 16" M4 Pro 24GB/512GB Space Black', 16.2),
        ('Apple MacBook Neo 13" A18 Pro 8GB/256GB Silver', 13.0),
        # ksenukai's shape: the part number after the family, the size further on.
        (
            'Portatīvais dators Apple MacBook Pro MGE94ZE/A, M5 Max, 48 GB, 2 TB, 16 ", 40-Core',
            16.2,
        ),
    ],
)
def test_a_macbook_s_screen_is_the_one_apple_built(title, screen):
    assert axis(title, "screen_inch", brand="Apple") == screen


def test_a_thousand_gigabytes_is_a_terabyte():
    """Drives are sold in decimal terabytes; `1000 GB` and `1 TB` are one drive."""
    from app.features.offers.normalization.categories.laptops import megabytes

    assert megabytes("1000", "GB") == megabytes("1", "TB") == 1048576
    assert megabytes("2000", "GB") == megabytes("2", "TB")
    assert megabytes("512", "GB") == 524288
    assert megabytes("1500", "GB") == 1536000


def test_a_nordic_keyboard_on_apple_s_ks_part_number_is_the_swedish_one():
    """Apple makes no Nordic keyboard; euronics calls its Swedish-Finnish `KS` one that."""
    words = Vocabulary(
        category_names=VOCABULARY.category_names,
        brand_names=VOCABULARY.brand_names,
        attribute_names={
            **VOCABULARY.attribute_names,
            normalize_attribute_name("key arrangement"): "keyboard_layout",
        },
        values={"keyboard_layout": {**VOCABULARY.values["keyboard_layout"], "nordic": "nordic"}},
    )
    fields = read(
        {
            "title": "Apple MacBook Air 13 (2026), M5, 10C/8C, 16 GB, 512 GB, SWE, silver",
            "brand": "Apple",
            "mpn": "MDH74KS/A",
            "attributes": {"key arrangement": "NORDIC"},
        },
        source_slug="euronics-laptops",
        shop_slug="euronics",
        category="laptops",
        vocabulary=words,
    )
    assert fields["identity"]["keyboard_layout"] == "swedish"
