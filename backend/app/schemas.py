from pydantic import BaseModel, Field


class Button(BaseModel):
    text: str
    data: str | None = None
    url: str | None = None


class RecOut(BaseModel):
    ext_id: str
    title: str
    url: str | None = None
    is_paid: bool = False
    kind: str = "article"
    benefit: str | None = None
    reason: str | None = None


class ChatRequest(BaseModel):
    tg_id: int
    chat_id: int | None = None
    text: str = Field(max_length=4000)


class CallbackRequest(BaseModel):
    tg_id: int
    chat_id: int | None = None
    data: str = Field(max_length=200)


class ChatResponse(BaseModel):
    text: str
    buttons: list[list[Button]] = Field(default_factory=list)
    recommendations: list[RecOut] = Field(default_factory=list)
    action: str | None = None
    typing: bool = False


class ProfileOut(BaseModel):
    stage: str | None = None
    industry: str | None = None
    legal_form: str | None = None
    tax_regime: str | None = None
    main_task: str | None = None
    experience: str | None = None
    time_budget: str | None = None


class ReminderOut(BaseModel):
    id: str
    type: str
    title: str
    description: str
    active: bool
    next_run_at: str | None = None


def rows(buttons: list[Button], per_row: int = 3) -> list[list[Button]]:
    return [buttons[i : i + per_row] for i in range(0, len(buttons), per_row)]
