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
        ("Lenovo ThinkPad P14s Gen 7 14 WUXGA AMD R5 AI PRO 440/16GB/512GB", "AMD Ryzen 5 PRO 440"),
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
