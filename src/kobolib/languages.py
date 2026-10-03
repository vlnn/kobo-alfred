from __future__ import annotations

import re

ENGLISH_NAMES = {
    "be": "belarusian",
    "bel": "belarusian",
    "cs": "czech",
    "ces": "czech",
    "cze": "czech",
    "de": "german",
    "deu": "german",
    "ger": "german",
    "en": "english",
    "eng": "english",
    "es": "spanish",
    "spa": "spanish",
    "fr": "french",
    "fra": "french",
    "fre": "french",
    "it": "italian",
    "ita": "italian",
    "ja": "japanese",
    "jpn": "japanese",
    "nl": "dutch",
    "nld": "dutch",
    "dut": "dutch",
    "pl": "polish",
    "pol": "polish",
    "pt": "portuguese",
    "por": "portuguese",
    "ru": "russian",
    "rus": "russian",
    "sv": "swedish",
    "swe": "swedish",
    "uk": "ukrainian",
    "ukr": "ukrainian",
    "zh": "chinese",
    "zho": "chinese",
    "chi": "chinese",
}
REGION = re.compile(r"[-_].*$")


def language_code(raw: str) -> str:
    return REGION.sub("", raw.strip()).lower()


def english_name(raw: str) -> str:
    return ENGLISH_NAMES.get(language_code(raw), "")


def searchable_language(raw: str) -> str:
    return " ".join(part for part in (raw.strip(), english_name(raw)) if part)
