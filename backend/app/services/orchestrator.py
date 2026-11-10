import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Profile, RecShown, User
from app.schemas import Button, CallbackRequest, ChatRequest, ChatResponse, RecOut, rows
from app.services import flows
from app.services import tax_calendar as tc
from app.services.context import (
    add_turn,
    apply_slots,
    clear_keys,
    get_profile,
    get_user,
    log_event,
    profile_dict,
    recent_history,
    set_state,
    utcnow,
)
from app.services.intent import (
    DEFAULT_CLARIFY,
    Intent,
    asks_paid_retell,
    classify,
    looks_like_injection,
)
from app.services.links import with_utm
from app.services.llm import get_llm
from app.services.pii import mask_pii
from app.services.profile_rules import (
    LEGAL_LABELS,
    SLOTS,
    STAGE_LABELS,
    TASK_LABELS,
    extract_slots,
    summarize,
)
from app.services.rag import Hit, generate_answer, relevant, search
from app.services.recommender import Rec, recommend
from app.services.reminders import manage_command

log = logging.getLogger(__name__)

EXAMPLES = [
    "Как выбрать налоговый режим для кофейни?",
    "С чего начать свой бизнес?",
    "Напоминай мне платить налоги",
]

REFUSAL_SCOPE = "Я помогаю только с вопросами о бизнесе и обучении на «Альфа-Курсе». С чем могу помочь по этим темам?"
SLOT_LABELS = {
    "stage": "Стадия",
    "industry": "Сфера",
    "legal_form": "Форма бизнеса",
    "tax_regime": "Налоговый режим",
    "main_task": "Главная задача",
    "experience": "Опыт",
    "time_budget": "Время на обучение",
}
SLOT_OPTIONS = {
    "stage": STAGE_LABELS,
    "legal_form": LEGAL_LABELS,
    "tax_regime": tc.REGIME_LABELS,
    "main_task": TASK_LABELS,
}
ENUM_SLOTS = {"stage", "legal_form", "tax_regime", "main_task"}


def example_buttons() -> list[list[Button]]:
    return rows([Button(text=t[:40], data=f"ex:{i}") for i, t in enumerate(EXAMPLES)], 1)


def onboarding_buttons() -> list[list[Button]]:
    stage = [Button(text=label, data=f"ob:stage:{key}") for key, label in list(STAGE_LABELS.items())[:3]]
    return [*example_buttons(), stage, [Button(text="Пропустить", data="ob:skip")]]


async def handle_start(session: AsyncSession, req: ChatRequest) -> ChatResponse:
    user = await get_user(session, req.tg_id, req.chat_id)
    await log_event(session, user.id, "start", {})
    return ChatResponse(
        text=(
            "Привет! Я помощник «Альфа-Курса». Отвечаю на вопросы по налогам, учёту, маркетингу и запуску бизнеса, "
            "подбираю материалы и напоминаю об обучении и налоговых сроках.\n\n"
            "Просто задайте вопрос своими словами или выберите пример. "
            "Хотите, чтобы советы были точнее? Ответьте, на каком вы этапе, или нажмите «Пропустить»."
        ),
        buttons=onboarding_buttons(),
    )


def first_sentences(text: str | None, count: int = 2, limit: int = 260) -> str | None:
    if not text:
        return None
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    result = " ".join(parts[:count])
    return result[:limit].rstrip() + ("…" if len(result) > limit else "")


def to_rec_out(rec: Rec, user_hash: str, content: str = "rec") -> RecOut:
    return RecOut(
        ext_id=rec.ext_id,
        title=rec.title,
        url=with_utm(rec.url, content, rec.ext_id, user_hash),
        is_paid=rec.is_paid,
        kind=rec.kind,
        benefit=first_sentences(rec.description) if rec.is_paid else None,
        reason=rec.reason,
    )


def sources_text(hits: list[Hit], user_hash: str) -> str:
    lines = []
    for i, h in enumerate(hits, start=1):
        url = with_utm(h.url, "src", h.ext_id, user_hash)
        lines.append(f"[{i}] {h.title}" + (f" — {url}" if url else ""))
    return "\n".join(lines)


def clean_slots(raw: dict[str, str]) -> dict[str, str]:
    result = {}
    for slot, value in raw.items():
        if slot not in SLOTS:
            continue
        if slot in ENUM_SLOTS and value not in SLOT_OPTIONS[slot]:
            continue
        if slot not in ENUM_SLOTS and (len(value) > 40 or not re.fullmatch(r"[\w\s\-]+", value, re.U)):
            continue
        result[slot] = value
    return result


def feedback_buttons(with_remind: bool = True) -> list[list[Button]]:
    result = [[
        Button(text="👍", data="fb:up"),
        Button(text="👎", data="fb:down"),
        Button(text="Ещё по теме", data="more"),
    ]]
    if with_remind:
        result.append([Button(text="Напомнить изучить", data="rm:learn")])
    return result


async def handle_chat(session: AsyncSession, req: ChatRequest) -> ChatResponse:
    now = utcnow()
    user = await get_user(session, req.tg_id, req.chat_id)
    profile = await get_profile(session, user)
    masked = mask_pii(req.text.strip())
    history = await recent_history(session, user.id)
    await add_turn(session, user.id, "user", masked)
    response, intent_name = await route(session, user, profile, masked, history, now)
    await add_turn(session, user.id, "assistant", response.text, intent_name)
    return response


async def route(
    session: AsyncSession, user: User, profile: Profile, text: str, history: list[str], now
) -> tuple[ChatResponse, str]:
    state = user.state or {}

    if state.get("flow") == "reminder" and "rem" in state:
        reply = await flows.flow_text(session, user, profile, text, now)
        if reply is not None:
            return reply, "reminder_flow"

    if state.get("flow") == "profile_text":
        slot = state.get("slot")
        value = clean_slots({slot: text}).get(slot)
        clear_keys(user, "flow", "slot")
        if value:
            apply_slots(profile, {slot: value}, 1.0)
            return ChatResponse(text=f"Записал: {SLOT_LABELS[slot].lower()} — {value}."), "profile"
        return ChatResponse(text="Не получилось распознать. Попробуйте ещё раз через /profile."), "profile"

    if looks_like_injection(text):
        await log_event(session, user.id, "injection_blocked", {})
        return ChatResponse(text=REFUSAL_SCOPE, buttons=example_buttons()), "out_of_scope"

    if asks_paid_retell(text):
        return await paid_retell_reply(session, user, text), "paid_guard"

    command = manage_command(text)
    if command:
        active = [r for r in await flows.list_for_user(session, user.id) if r.active]
        if active:
            reply = await flows.manage_text(session, user, text, command, now)
            if reply is not None:
                return reply, "reminder_manage"

    intent = await classify(text, history, get_llm())
    slots = extract_slots(text)
    changed = apply_slots(profile, slots, 0.85)
    llm_slots = {k: v for k, v in clean_slots(intent.slots).items() if k not in slots}
    changed |= apply_slots(profile, llm_slots, 0.6)
    if changed:
        await log_event(session, user.id, "profile_updated", {"slots": sorted(changed)})

    if intent.intent == "smalltalk":
        thanks = re.search(r"спасибо|благодар", text, re.I)
        reply = "Пожалуйста! Если появятся вопросы — пишите." if thanks else "Здравствуйте! Чем могу помочь? Можно выбрать пример:"
        return ChatResponse(text=reply, buttons=example_buttons()), "smalltalk"

    if intent.intent == "reminder_intent":
        return await flows.start_reminder(session, user, profile, text, now), "reminder_intent"

    if intent.intent == "ambiguous":
        return await clarify_reply(session, user, text, intent), "ambiguous"

    return await answer_question(session, user, profile, text, intent, history), intent.intent


async def clarify_reply(session: AsyncSession, user: User, text: str, intent: Intent) -> ChatResponse:
    options = intent.clarify_options or list(DEFAULT_CLARIFY)
    set_state(user, pending={"question": text, "options": options})
    await log_event(session, user.id, "clarification_asked", {})
    buttons = rows([Button(text=o[:30], data=f"clar:{i}") for i, o in enumerate(options)], 3)
    return ChatResponse(text="Уточните, пожалуйста, что именно вас интересует?", buttons=buttons)


async def paid_retell_reply(session: AsyncSession, user: User, text: str) -> ChatResponse:
    hits = await search(session, text, limit=8)
    paid = next((h for h in hits if h.is_paid), None)
    await log_event(session, user.id, "paid_content_request", {})
    if paid is None:
        return ChatResponse(
            text="Содержание платных материалов я не пересказываю. Могу ответить на ваш вопрос по открытым материалам — задайте его."
        )
    benefit = first_sentences(paid.description) or "Подробности — на странице курса."
    link = with_utm(paid.url, "rec", paid.ext_id, user.tg_id_hash)
    price = f"\nСтоимость: {paid.price} ₽." if paid.price else ""
    return ChatResponse(
        text=(
            f"Содержание платных уроков я не пересказываю. Но могу сказать, чем полезен курс «{paid.title}»:\n"
            f"{benefit}{price}\nПодробнее — на платформе."
        ),
        recommendations=[
            RecOut(ext_id=paid.ext_id, title=paid.title, url=link, is_paid=True, kind=paid.kind, benefit=benefit)
        ],
    )


async def out_of_scope_reply(session: AsyncSession, user: User, text: str, near: list[Hit], best: float) -> ChatResponse:
    await log_event(session, user.id, "no_answer", {"q": text[:300], "best": round(best, 3)})
    lines = ["В базе «Альфа-Курса» ответа на этот вопрос нет, а выдумывать я не буду."]
    suggestions = [h for h in near if not h.is_paid and h.score >= 0.4][:3]
    if suggestions:
        lines.append("Возможно, пригодятся ближайшие материалы:")
        lines += [f"• {h.title}" + (f" — {with_utm(h.url, 'rec', h.ext_id, user.tg_id_hash)}" if h.url else "") for h in suggestions]
    else:
        lines.append("Я могу помочь с налогами и режимами, регистрацией бизнеса, учётом, маркетингом и продажами.")
    return ChatResponse(text="\n".join(lines), buttons=example_buttons())


def needs_legal_form_question(profile: Profile, question: str, hits: list[Hit], state: dict) -> bool:
    if profile.legal_form:
        return False
    if state.get("answer_n", 0) - state.get("asked_legal_at", -10) < 4:
        return False
    tax_related = bool(re.search(r"налог|усн|режим|взнос|патент|ндс", question, re.I)) or any(
        "налог" in t.lower() for h in hits[:2] for t in h.topics
    )
    return tax_related


async def answer_question(
    session: AsyncSession, user: User, profile: Profile, text: str, intent: Intent, history: list[str]
) -> ChatResponse:
    settings = get_settings()
    hits_all = await search(session, text, limit=8)
    free = [h for h in hits_all if not h.is_paid]
    rel = relevant(free)[:5]
    best = free[0].score if free else 0.0
    if not rel or (intent.intent == "out_of_scope" and best < settings.relevance_threshold * 1.15):
        return await out_of_scope_reply(session, user, text, free, best)

    prof = profile_dict(profile)
    answer, used_llm = await generate_answer(get_llm(), text, rel, summarize(prof), history)
    state = user.state or {}
    body = answer + "\n\nИсточники:\n" + sources_text(rel[:3], user.tg_id_hash)

    recs: list[Rec] = []
    if user.ab_group != "A":
        paid_allowed = state.get("answers_since_paid", 2) >= 2
        recs = (await recommend(session, user.id, hits_all, text, prof, intent.topic, paid_allowed))[:2]
    for rec in recs:
        session.add(RecShown(user_id=user.id, material_ext_id=rec.ext_id, reason=rec.reason))
    shown_paid = any(r.is_paid for r in recs)

    answer_n = state.get("answer_n", 0) + 1
    first_free = next((r for r in recs if not r.is_paid), None)
    anchor = {"ext_id": first_free.ext_id, "title": first_free.title} if first_free else {"ext_id": rel[0].ext_id, "title": rel[0].title}
    shown = list(dict.fromkeys([*state.get("shown", []), *[h.ext_id for h in rel[:3]], *[r.ext_id for r in recs]]))[-40:]
    set_state(
        user,
        answer_n=answer_n,
        answers_since_paid=0 if shown_paid else state.get("answers_since_paid", 2) + 1,
        last_material=anchor,
        last_question=text,
        last_rec_ids=[r.ext_id for r in recs],
        shown=shown,
    )
    clear_keys(user, "pending")

    buttons = feedback_buttons()
    if needs_legal_form_question(profile, text, rel, state):
        set_state(user, asked_legal_at=answer_n)
        body += "\n\nКстати, вы уже зарегистрированы как ИП или только планируете?"
        buttons.append([
            Button(text="ИП", data="slot:legal_form:ip"),
            Button(text="ООО", data="slot:legal_form:ooo"),
            Button(text="Пока планирую", data="slot:stage:start"),
        ])

    await log_event(
        session,
        user.id,
        "answer_given",
        {"intent": intent.intent, "hits": len(rel), "llm": used_llm, "recs": len(recs), "paid_shown": shown_paid},
    )
    return ChatResponse(
        text=body,
        buttons=buttons,
        recommendations=[to_rec_out(r, user.tg_id_hash) for r in recs],
    )


async def more_reply(session: AsyncSession, user: User) -> ChatResponse:
    state = user.state or {}
    question = state.get("last_question")
    if not question:
        return ChatResponse(text="Сначала задайте вопрос — потом я подберу ещё материалы по теме.")
    hits = await search(session, question, limit=12, include_paid=False)
    seen = set(state.get("shown", []))
    fresh = [h for h in hits if h.ext_id not in seen and h.score >= 0.45][:3]
    if not fresh:
        return ChatResponse(text="По этой теме больше ничего подходящего не нашёл. Попробуйте уточнить вопрос.")
    set_state(user, shown=list(dict.fromkeys([*seen, *[h.ext_id for h in fresh]]))[-40:])
    lines = ["Ещё по теме:"]
    for h in fresh:
        url = with_utm(h.url, "rec", h.ext_id, user.tg_id_hash)
        lines.append(f"• {h.title}" + (f" — {url}" if url else ""))
    return ChatResponse(text="\n".join(lines))


async def feedback_reply(session: AsyncSession, user: User, value: str) -> ChatResponse:
    ids = (user.state or {}).get("last_rec_ids", [])
    if ids:
        result = await session.execute(
            select(RecShown)
            .where(RecShown.user_id == user.id, RecShown.material_ext_id.in_(ids))
            .order_by(RecShown.id.desc())
            .limit(len(ids))
        )
        for shown in result.scalars():
            shown.reaction = value
    await log_event(session, user.id, f"feedback_{value}", {})
    if value == "down":
        return ChatResponse(text="Спасибо, учту. Если хотите, переформулируйте вопрос — попробую ответить точнее.")
    return ChatResponse(text="Рад, что помог! Если хотите, напомню вернуться к этой теме — нажмите «Напомнить изучить».")


async def profile_response(session: AsyncSession, user: User) -> ChatResponse:
    profile = await get_profile(session, user)
    lines = ["Что я о вас знаю:"]
    for slot in SLOTS:
        value = getattr(profile, slot)
        if value and slot in SLOT_OPTIONS:
            value = SLOT_OPTIONS[slot].get(value, value)
        lines.append(f"• {SLOT_LABELS[slot]}: {value or '—'}")
    lines.append("\nЭти данные нужны только для более точных советов. Что изменить?")
    buttons = rows([Button(text=SLOT_LABELS[s], data=f"pf:ask:{s}") for s in SLOTS if s in {"stage", "industry", "legal_form", "tax_regime", "main_task"}], 3)
    return ChatResponse(text="\n".join(lines), buttons=buttons)


async def profile_callback(session: AsyncSession, user: User, data: str) -> ChatResponse:
    profile = await get_profile(session, user)
    parts = data.split(":")
    action, slot = parts[1], parts[2]
    if slot not in SLOTS:
        return ChatResponse(text="Не понял, что менять.")
    if action == "ask":
        if slot in SLOT_OPTIONS:
            buttons = rows([Button(text=label, data=f"pf:set:{slot}:{key}") for key, label in SLOT_OPTIONS[slot].items()], 2)
            buttons.append([Button(text="Очистить", data=f"pf:set:{slot}:none")])
            return ChatResponse(text=f"{SLOT_LABELS[slot]}: выберите вариант", buttons=buttons)
        set_state(user, flow="profile_text", slot=slot)
        return ChatResponse(text=f"Напишите: {SLOT_LABELS[slot].lower()} (коротко, одним-двумя словами).")
    value = parts[3]
    if value == "none":
        setattr(profile, slot, None)
        conf = dict(profile.slot_confidence or {})
        conf.pop(slot, None)
        profile.slot_confidence = conf
        return ChatResponse(text=f"Очистил: {SLOT_LABELS[slot].lower()}.")
    apply_slots(profile, {slot: value}, 1.0)
    label = SLOT_OPTIONS.get(slot, {}).get(value, value)
    return ChatResponse(text=f"Записал: {SLOT_LABELS[slot].lower()} — {label}.")


async def handle_callback(session: AsyncSession, req: CallbackRequest) -> ChatResponse:
    now = utcnow()
    user = await get_user(session, req.tg_id, req.chat_id)
    profile = await get_profile(session, user)
    data = req.data
    prefix = data.split(":")[0]
    state = user.state or {}

    if prefix == "ex":
        idx = int(data.split(":")[1])
        return await handle_chat(session, ChatRequest(tg_id=req.tg_id, chat_id=req.chat_id, text=EXAMPLES[idx]))
    if prefix == "ob":
        parts = data.split(":")
        if parts[1] == "stage":
            apply_slots(profile, {"stage": parts[2]}, 1.0)
            buttons = rows([Button(text=label, data=f"ob:task:{key}") for key, label in TASK_LABELS.items()], 2)
            buttons.append([Button(text="Пропустить", data="ob:skip")])
            return ChatResponse(text="Что сейчас важнее всего?", buttons=buttons)
        if parts[1] == "task":
            apply_slots(profile, {"main_task": parts[2]}, 1.0)
        return ChatResponse(text="Спасибо! Теперь задайте вопрос или выберите пример.", buttons=example_buttons())
    if prefix == "clar":
        pending = state.get("pending")
        idx = int(data.split(":")[1])
        if not pending or idx >= len(pending["options"]):
            return ChatResponse(text="Давайте ещё раз: о чём вы хотите узнать?")
        option = pending["options"][idx]
        clear_keys(user, "pending")
        if option.lower().startswith("друг"):
            return ChatResponse(text="Опишите свой вопрос подробнее, и я постараюсь помочь.")
        return await handle_chat(
            session, ChatRequest(tg_id=req.tg_id, chat_id=req.chat_id, text=f"{pending['question']} — {option}")
        )
    if prefix == "slot":
        _, slot, value = data.split(":")
        apply_slots(profile, {slot: value}, 1.0)
        await log_event(session, user.id, "profile_updated", {"slots": [slot]})
        return ChatResponse(text="Спасибо, учту в следующих ответах.")
    if prefix == "fb":
        return await feedback_reply(session, user, data.split(":")[1])
    if data == "more":
        return await more_reply(session, user)
    if prefix == "rm":
        material = state.get("last_material")
        return await flows.start_reminder(session, user, profile, "напомни продолжить обучение", now, material=material)
    if prefix == "rf":
        return await flows.flow_callback(session, user, profile, data, now)
    if prefix == "rem":
        return await flows.reminder_action(session, user, data, now)
    if prefix == "pf":
        return await profile_callback(session, user, data)
    return ChatResponse(text="Не понял команду.")
