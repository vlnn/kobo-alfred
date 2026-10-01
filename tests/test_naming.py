import pytest

from kobolib.naming import author_folder, canonical_name, destination, fat_safe, genre_root
from tests.test_alfred import row


@pytest.mark.parametrize(
    "authors, folder",
    [
        ("Rowan Teague", "Teague, Rowan"),
        ("Teague, Rowan", "Teague, Rowan"),
        ("Rowan Teague; Petra Marlowe", "Teague, Rowan"),
        ("Morwenna O'Hare", "O'Hare, Morwenna"),
        ("Harriet V. Okonkwo", "Okonkwo, Harriet V."),
        ("Тіґ Ровен", "Ровен, Тіґ"),
        ("Plato", "Plato"),
        ("", ""),
    ],
)
def test_author_folder(authors, folder):
    assert author_folder(authors) == folder, f"{authors!r} should file under {folder!r}"


@pytest.mark.parametrize(
    "overrides, name",
    [
        ({}, "Newport, Cal - Deep Work (Focus 02) (2016).epub"),
        ({"series": "", "series_index": ""}, "Newport, Cal - Deep Work (2016).epub"),
        ({"year": ""}, "Newport, Cal - Deep Work (Focus 02).epub"),
        ({"authors": ""}, "Deep Work (Focus 02) (2016).epub"),
        ({"series_index": "1-3"}, "Newport, Cal - Deep Work (Focus 01-03) (2016).epub"),
        ({"series_index": "12"}, "Newport, Cal - Deep Work (Focus 12) (2016).epub"),
        ({"partial": True}, "Newport, Cal - Deep Work (Focus 02) (2016).epub.part"),
        ({"format": "fb2"}, "Newport, Cal - Deep Work (Focus 02) (2016).fb2"),
        ({"title": "Salt: A Signal?"}, "Newport, Cal - Salt_ A Signal_ (Focus 02) (2016).epub"),
    ],
)
def test_canonical_name(overrides, name):
    assert canonical_name(row(**overrides)) == name, f"{overrides} should name the file {name!r}"


@pytest.mark.parametrize(
    "raw, safe",
    [
        ('a:b?c*d|e"f<g>h/i\\j', "a_b_c_d_e_f_g_h_i_j"),
        ("  double   space  ", "double space"),
        ("trailing. ", "trailing"),
        ("x" * 300 + ".epub", "x" * 250 + ".epub"),
    ],
)
def test_fat_safe(raw, safe):
    assert fat_safe(raw) == safe, f"{raw!r} should become {safe!r}"


def test_fat_safe_truncates_on_utf8_bytes_not_chars():
    name = "ї" * 200 + ".fb2"
    safe = fat_safe(name)
    assert len(safe.encode()) <= 255 and safe.endswith(".fb2"), "long names should be cut at 255 bytes keeping the extension"


def test_genre_root_prefers_existing_folder():
    folders = {"01_Fiction", "01_Fiction/01_Sci-Fi_Fantasy", "01_Fiction/01_Sci-Fi_Fantasy/Series", "02_NonFiction"}
    assert genre_root("fiction/sci-fi_fantasy", folders) == "01_Fiction/01_Sci-Fi_Fantasy", "an existing folder for the genre should be reused"
    assert genre_root("fiction/mystery", folders) == "01_Fiction/mystery", "a new genre nests under the existing parent"
    assert genre_root("games/go", folders) == "games/go", "an unknown genre becomes its own path"


@pytest.mark.parametrize(
    "overrides, series_count, rel_path",
    [
        ({}, 2, "01_Fiction/01_Sci-Fi_Fantasy/Newport, Cal/Focus/Newport, Cal - Deep Work (Focus 02) (2016).epub"),
        ({}, 1, "01_Fiction/01_Sci-Fi_Fantasy/Newport, Cal/Newport, Cal - Deep Work (Focus 02) (2016).epub"),
        ({"series": "", "series_index": ""}, 0, "01_Fiction/01_Sci-Fi_Fantasy/Newport, Cal/Newport, Cal - Deep Work (2016).epub"),
        ({"authors": ""}, 0, "01_Fiction/01_Sci-Fi_Fantasy/Deep Work (Focus 02) (2016).epub"),
    ],
)
def test_destination(overrides, series_count, rel_path):
    folders = {"01_Fiction", "01_Fiction/01_Sci-Fi_Fantasy"}
    got = destination(row(**overrides), "fiction/sci-fi_fantasy", folders, series_count)
    assert got == rel_path, f"{overrides} with {series_count} in series should land at {rel_path!r}"
