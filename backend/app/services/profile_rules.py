import re

SLOTS = ("stage", "industry", "legal_form", "tax_regime", "main_task", "experience", "time_budget")

STAGE_LABELS = {"idea": "Только думаю", "start": "Запускаюсь", "running": "Бизнес работает", "growth": "Развиваю бизнес"}
LEGAL_LABELS = {"ip": "ИП", "ooo": "ООО", "selfemployed": "Самозанятый"}
TASK_LABELS = {
    "taxes": "Налоги и учёт",
    "marketing": "Маркетинг и продажи",
    "start": "Запуск бизнеса",
    "team": "Команда и процессы",
}

INDUSTRY_KEYWORDS = {
    "общепит": ("кофейн", "кафе", "ресторан", "столов", "пекарн", "общепит", "фудтрак", "бар "),
    "розница": ("магазин", "розниц", "бутик", "маркетплейс", "wildberries", "вайлдберриз", "ozon", "озон"),
    "услуги": ("салон", "барбер", "парикмахер", "ногт", "консалт", "репетитор", "клининг", "фитнес"),
    "производство": ("производств", "цех", "мастерск"),
    "it": ("it-", "разработк", "приложени", "сайт", "программ"),
    "образование": ("курсы", "школ", "обучени"),
}


def extract_legal_form(text: str) -> str | None:
    t = text.lower()
    if re.search(r"самозанят|\bнпд\b|профессиональн\w+ доход", t):
        return "selfemployed"
    if re.search(r"\bооо\b|общество с ограниченной", t):
        return "ooo"
    if re.search(r"(?<![а-яa-z])ип(?![а-яa-z])|индивидуальн\w+ предпринимател", t):
        return "ip"
    return None


def extract_tax_regime(text: str) -> str | None:
    t = text.lower().replace("ё", "е")
    if re.search(r"аусн|автоматизированн\w+ упрощ", t):
        return "ausn"
    if re.search(r"патент", t):
        return "patent"
    if re.search(r"\bнпд\b|самозанят|профессиональн\w+ доход", t):
        return "npd"
    if re.search(r"\bосн\b|\bосно\b|общая система|общий режим", t):
        return "osn"
    if re.search(r"усн|упрощенк|упрощенн", t):
        if re.search(r"доход\w*\s*(минус|-|−)\s*расход|15\s*%", t):
            return "usn_income_expense"
        if re.search(r"доход|6\s*%", t):
            return "usn_income"
    if re.search(r"доход\w*\s*(минус|-|−)\s*расход", t):
        return "usn_income_expense"
    return None


def extract_industry(text: str) -> str | None:
    t = text.lower() + " "
    for industry, stems in INDUSTRY_KEYWORDS.items():
        if any(stem in t for stem in stems):
            return industry
    return None


def extract_stage(text: str) -> str | None:
    t = text.lower()
    if re.search(r"хочу открыть|планирую|собираюсь|думаю открыть|только начина|с чего начать|идея", t):
        return "start"
    if re.search(r"уже работа|давно работа|у меня (?:есть )?(?:свой )?бизнес|развива|масштабир", t):
        return "running"
    return None


def extract_main_task(text: str) -> str | None:
    t = text.lower()
    if re.search(r"налог|бухгалтер|отчетн|отчётн|взнос|учет|учёт", t):
        return "taxes"
    if re.search(r"маркетинг|реклам|продаж|клиент", t):
        return "marketing"
    if re.search(r"открыть|регистрац|запуск", t):
        return "start"
    if re.search(r"команд|сотрудник|найм|процесс", t):
        return "team"
    return None


def extract_slots(text: str) -> dict[str, str]:
    found = {
        "legal_form": extract_legal_form(text),
        "tax_regime": extract_tax_regime(text),
        "industry": extract_industry(text),
        "stage": extract_stage(text),
        "main_task": extract_main_task(text),
    }
    return {k: v for k, v in found.items() if v}


def summarize(profile: dict[str, str | None]) -> str:
    parts = []
    if profile.get("stage"):
        parts.append(f"стадия: {profile['stage']}")
    if profile.get("industry"):
        parts.append(f"сфера: {profile['industry']}")
    if profile.get("legal_form"):
        parts.append(f"форма: {profile['legal_form']}")
    if profile.get("tax_regime"):
        parts.append(f"налоговый режим: {profile['tax_regime']}")
    if profile.get("main_task"):
        parts.append(f"главная задача: {profile['main_task']}")
    return "; ".join(parts) if parts else "неизвестен"
