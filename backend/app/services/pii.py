import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_USERNAME = re.compile(r"(?<![\w@])@[A-Za-z][A-Za-z0-9_]{3,31}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+7|8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)")
_LONG_NUMBER = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_INN = re.compile(r"(?<!\d)(?:\d{12}|\d{10})(?!\d)")
_NAME = re.compile(
    r"(?i)\b(меня зовут|моя фамилия|мое имя|моё имя|я —|я -)\s+"
    r"([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){0,2})"
)

_RULES = (
    (_EMAIL, "[email]"),
    (_USERNAME, "[username]"),
    (_PHONE, "[телефон]"),
    (_LONG_NUMBER, "[номер]"),
    (_INN, "[инн]"),
)


def mask_pii(text: str) -> str:
    if not text:
        return text
    result = text
    for pattern, replacement in _RULES:
        result = pattern.sub(replacement, result)
    result = _NAME.sub(lambda m: f"{m.group(1)} [имя]", result)
    return result


def contains_pii(text: str) -> bool:
    return mask_pii(text) != text
