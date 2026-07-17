"""Arabic text normalization helpers.

Searches and autocomplete should feel forgiving for common spelling
variations: hamza forms, ta marbuta vs ha, diacritics/tashkeel, etc.
"""

import re
import unicodedata

# Tashkeel, tatweel and other combining marks commonly added/omitted.
_ARABIC_MARKS_RE = re.compile(
    r"[\u0610-\u061A\u064B-\u065F\u0670\u0640]"
)

# Alef variants with hamza/madda/wasla -> bare alef.
_ALEF_VARIANTS_RE = re.compile(r"[\u0622\u0623\u0625]")

# Hamza on waw (ؤ) -> و ; hamza on yeh (ئ) -> ي.
_MIDDLE_HAMZA_RE = re.compile(r"[\u0624\u0626]")


def normalize_arabic(text: str) -> str:
    """Return a normalized form of *text* for forgiving comparison.

    The normalization is intentionally conservative: it collapses the
    spelling differences users are most likely to hit when typing Arabic
    quickly (hamza, ta marbuta, diacritics) without over-aggressively
    merging distinct letters.
    """
    if text is None:
        return ""
    text = str(text).lower()
    text = _ARABIC_MARKS_RE.sub("", text)
    text = _ALEF_VARIANTS_RE.sub("ا", text)
    text = text.replace("\u0671", "ا")  # alef wasla
    text = _MIDDLE_HAMZA_RE.sub(
        lambda m: "و" if m.group(0) == "\u0624" else "ي", text
    )
    text = text.replace("\u0621", "")  # standalone hamza
    text = text.replace("\u0629", "\u0647")  # ta marbuta -> ha
    # Normalize Unicode compatibility forms (e.g. presentation forms) when
    # they sneak in from copy-paste.
    text = unicodedata.normalize("NFKC", text)
    return text
