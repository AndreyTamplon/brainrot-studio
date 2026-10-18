"""Deterministic checks for numeric mistakes that transcript similarity can hide."""

import re

from number_parser import parse_number

_DECIMAL = re.compile(
    r"\bцел(?:ая|ых|ую|ой|ым|ыми)\s+(?:и\s+)?"
    r"(?P<numerator>[а-яё\d\s-]{1,120}?)\s+"
    r"(?P<unit>десят|сот|тысячн|десятитысячн|стотысячн|миллионн)"
    r"(?:ая|ых|ую|ой|ым|ыми)\b",
    re.IGNORECASE,
)
_DENOMINATORS = {
    "десят": 10,
    "сот": 100,
    "тысячн": 1000,
    "десятитысячн": 10000,
    "стотысячн": 100000,
    "миллионн": 1000000,
}


def validate_decimal_speech(text):
    # A compound decimal's fractional part must be proper. Do not guess the intended value.
    for match in _DECIMAL.finditer(text):
        numerator = parse_number(match["numerator"].lower(), language="ru")
        if numerator is not None and numerator >= _DENOMINATORS[match["unit"].lower()]:
            raise ValueError(
                f"Invalid spoken decimal: '{match[0]}'. Check the value against the source and "
                "use the correct denominator (for example, 1.24 is 'одна целая двадцать четыре "
                "сотых', not 'десятых')."
            )
    return text
