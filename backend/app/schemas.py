from datetime import datetime
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, StringConstraints, Field, model_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Contact = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
Password = Annotated[str, StringConstraints(min_length=10, max_length=128)]
Login = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=3, max_length=64, pattern=r'^[a-z0-9_.-]+$')]


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class LoginInput(Input):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class StaffCreate(Input):
    name: Name
    login: Login
    password: Password
    role: Literal['operator', 'admin'] = 'operator'


class StaffEdit(Input):
    name: Name
    role: Literal['operator', 'admin']
    active: bool
    password: Password | None = None


class StaffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    login: str
    role: str
    active: bool
    created_at: datetime


class ItemInput(Input):
    name: Name
    active: bool = True
    sort_order: int = Field(default=0, ge=0, le=10000)


class ItemOut(ItemInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    group_id: int


class GroupOut(ItemInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    items: list[ItemOut]


class TicketCreate(Input):
    applicant_name: Name
    contact: Contact
    group_id: int = Field(gt=0)
    item_id: int = Field(gt=0)
    description: Description


class TicketAction(Input):
    action: Literal['take', 'assign', 'complete', 'reject']
    version: int = Field(ge=1)
    assignee_id: int | None = Field(default=None, gt=0)
    comment: Description | None = None

    @model_validator(mode='after')
    def required(self):
        if self.action == 'assign' and self.assignee_id is None:
            raise ValueError('Выберите исполнителя')
        if self.action in ('complete', 'reject') and not self.comment:
            raise ValueError('Укажите результат закрытия')
        return self


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    number: str
    source: str
    created_at: datetime
    updated_at: datetime
    applicant_name: str
    contact_snapshot: str
    group_id: int
    item_id: int
    description: str
    status: str
    assignee_id: int | None
    result: str | None
    closed_at: datetime | None
    version: int
    group: GroupOut
    item: ItemOut
    assignee: StaffOut | None


class HistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    action: str
    actor_type: str
    actor: StaffOut | None
    old_values: dict
    new_values: dict
    comment: str | None


class TicketDetail(TicketOut):
    history: list[HistoryOut]
    telegram_user_id: str | None = None
    telegram_username: str | None = None


class TicketPage(BaseModel):
    items: list[TicketOut]
    total: int
    page: int
    page_size: int


class CountRow(BaseModel):
    name: str
    count: int


class StatsOut(BaseModel):
    total: int
    statuses: dict[str, int]
    groups: list[CountRow] = []
    items: list[CountRow] = []
    assignees: list[CountRow] = []
