from pathlib import Path

import pytest

from kobolib.lint import (
    Finding,
    double_extensions,
    exact_duplicates,
    lint,
    noisy_names,
    opaque_names,
    title_duplicates,
)
from tests.test_alfred import row


def named(name: str, folder: str = "00_Inbox", **overrides):
    return row(rel_path=f"{folder}/{name}", folder=folder, **overrides)


def paths(findings: list[Finding]) -> list[list[str]]:
    return [f.rel_paths for f in findings]


@pytest.mark.parametrize(
    "name, title, authors, guessed, opaque",
    [
        ("7_815203.epub", "7_815203", "", True, True),
        ("512_904417.epub", "512_904417", "", True, True),
        ("smp9900000415626_7c1d2.epub", "smp9900000415626_7c1d2", "", True, True),
        ("annas-arch-0a1b2c3d4e5f.fb2", "annas-arch-0a1b2c3d4e5f", "", True, True),
        ("9f8e7d6c5b4a3_zorya.fb2", "9f8e7d6c5b4a3_zorya", "", True, True),
        ("fb2048576u_misto_bez_sontsia.fb2", "fb2048576u_misto_bez_sontsia", "", True, True),
        ("vorlak.fb2", "vorlak", "", True, True),
        ("ZYX.mobi", "ZYX", "", True, True),
        ("quiet-lantern.epub", "quiet-lantern", "", True, True),
        ("7_815203.epub", "Dhalgren", "", False, True),
        ("vorlak.fb2", "Vorlak", "", False, False),
        ("Learn_Ferrite_in_a_Month_of_Evenings.epub", "Learn_Ferrite_in_a_Month_of_Evenings", "", True, False),
        ("Orbital Gardening.pdf", "Orbital Gardening", "", True, False),
        ("1847 - Marta Velinska.epub", "1847", "Marta Velinska", True, False),
        ("Saltmarsh.epub", "Saltmarsh", "Ivor Penhale", True, False),
    ],
)
def test_opaque_names(name, title, authors, guessed, opaque):
    found = opaque_names([named(name, title=title, authors=authors, guessed=guessed)])
    assert bool(found) is opaque, f"{name!r} (guessed={guessed}) opaque should be {opaque}"


@pytest.mark.parametrize(
    "name, double",
    [
        ("Grell_Zmahannia.118822.fb2.mobi", True),
        ("Ember - 2014.epub.part", False),
        ("Tom 1.0.epub", False),
        ("x.fb2", False),
    ],
)
def test_double_extensions(name, double):
    assert bool(double_extensions([named(name)])) is double, f"{name!r} double extension should be {double}"


@pytest.mark.parametrize(
    "name, noisy",
    [
        (" Harriet V. Okonkwo - Tidal Minds (2023) - libgen.li.epub", True),
        ("Penhale, Ivor - Salt and Signal - libgen.li.epub", True),
        ("Marlowe, Petra - Finish Everything (2014, Quill &amp_ Lantern).epub", True),
        ("Copper Hymn -- Teodor Vaskiv -- 9780000000001 -- 0123456789abcdef0123456789abcdef -- Anna’s Archive.epub", True),
        ("Ashfall{Rowan Teague}(Lantern){100000001} libgen.li.epub", True),
        ("Learn_Ferrite_in_a_Month_of_Evenings.epub", True),
        ("Varga_Dovhi-Nochi_2_Zlam.400123.epub", True),
        ("pisnia-dlya-mandrivnyka.fb2", True),
        ("Teague Rowan - Ash and Ember (Book of the Grey Tide 01-02) - 2011.epub", False),
        ("01 Keel and Canvas - Morwenna O'Hare.epub", False),
    ],
)
def test_noisy_names(name, noisy):
    assert bool(noisy_names([named(name)])) is noisy, f"{name!r} noisy should be {noisy}"


def test_exact_duplicates_group_by_fingerprint():
    rows = [
        named("hlaskvyl.epub", folder="00_Inbox/bought", fingerprint="same"),
        named("hlaskvyl.epub", folder="00_Inbox/NOW", fingerprint="same"),
        named("other.epub", fingerprint="other"),
        named("no.epub", fingerprint=""),
        named("no2.epub", fingerprint=""),
    ]

    assert paths(exact_duplicates(rows)) == [["00_Inbox/bought/hlaskvyl.epub", "00_Inbox/NOW/hlaskvyl.epub"]], (
        "identical files should be grouped, empty fingerprints ignored"
    )


def test_title_duplicates_exclude_exact_copies_and_partials():
    rows = [
        named("Verdigris.fb2", title="Verdigris", norm_title="verdigris", format="fb2", fingerprint="a"),
        named("Verdigris.epub", title="Verdigris", norm_title="verdigris", format="epub", fingerprint="b"),
        named("Ember.epub", norm_title="ember", fingerprint="c"),
        named("Ember.epub.part", norm_title="ember", fingerprint="d", partial=True),
        named("Copy.epub", folder="x", norm_title="copy", fingerprint="e"),
        named("Copy.epub", folder="y", norm_title="copy", fingerprint="e"),
    ]

    found = title_duplicates(rows)

    assert paths(found) == [["00_Inbox/Verdigris.fb2", "00_Inbox/Verdigris.epub"]], (
        "same title in different complete files should be reported once; exact copies belong to another rule"
    )
    assert found[0].detail == "Verdigris: fb2, epub", "detail should list the formats"


def test_lint_runs_all_rules_in_order(tmp_path: Path):
    (tmp_path / "FSCK0000.000").write_bytes(b"")
    rows = [named("2_1.epub", title="2_1", fingerprint="x"), named("b.epub.part", partial=True, fingerprint="y")]

    rules = [f.rule for f in lint(rows, tmp_path)]

    assert rules == ["junk", "noisy_name", "opaque"], "findings should follow the rule order"


def test_author_inversions_are_reported():
    from kobolib.lint import author_inversions

    rows = [
        named("a.epub", folder="01_Fiction/Teague, Rowan"),
        named("b.epub", folder="01_Fiction/Teague, Rowan"),
        named("c.epub", folder="01_Fiction/Rowan, Teague"),
        named("d.epub", folder="01_Fiction/Marlowe, Petra"),
    ]

    found = author_inversions(rows)

    assert paths(found) == [["01_Fiction/Rowan, Teague/c.epub"]], "the folder with fewer books is the inverted one"
    assert found[0].detail.endswith("Teague, Rowan"), "detail should name the folder to merge into"
