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
    ],
)
def test_the_name_is_what_stands_in_front_of_the_configuration(title, brand, model):
    assert laptop(title, brand)["model"] == model


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
