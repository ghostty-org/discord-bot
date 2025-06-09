import datetime as dt
from typing import Annotated, Literal, NamedTuple

from pydantic import (
    AliasChoices,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
)

from app.utils import truncate


def state_validator(value: object) -> bool:
    match value:
        case bool():
            return value
        case "open" | "closed":
            return value == "closed"
        case _:
            msg = "`closed` must be a bool or a string of 'open' or 'closed'"
            raise ValueError(msg)


class GitHubUser(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(alias="login")
    # `html_url` comes before `url` to prefer the human-readable GitHub page link
    # when both fields are present
    url: str = Field(validation_alias=AliasChoices("html_url", "url"))
    icon_url: str = Field(validation_alias=AliasChoices("icon_url", "avatar_url"))


class Reactions(BaseModel):
    model_config = ConfigDict(frozen=True)

    plus_one: int
    minus_one: int
    laugh: int
    confused: int
    heart: int
    hooray: int
    eyes: int
    rocket: int


class Entity(BaseModel):
    model_config = ConfigDict(frozen=True)

    number: int
    title: str
    body: str | None
    reactions: Reactions | None = None
    html_url: str
    user: GitHubUser
    created_at: dt.datetime

    @property
    def kind(self) -> str:
        if not (name := type(self).__name__):
            return name
        return name[0] + "".join(f" {c}" if c.isupper() else c for c in name[1:])


class Issue(Entity):
    closed: Annotated[bool, Field(alias="state"), BeforeValidator(state_validator)]
    state_reason: Literal["completed", "reopened", "not_planned", "duplicate"] | None


class PullRequest(Entity):
    closed: Annotated[bool, Field(alias="state"), BeforeValidator(state_validator)]
    draft: bool
    merged: bool


class Discussion(Entity):
    answered: bool | None


class EntityGist(NamedTuple):
    owner: str
    repo: str
    number: int

    def __str__(self) -> str:
        return f"{self.owner}/{self.repo}#{self.number}"


class Comment(BaseModel):
    model_config = ConfigDict(frozen=True)

    author: GitHubUser
    body: str
    reactions: Reactions | None = None
    entity: Entity
    entity_gist: EntityGist
    created_at: dt.datetime
    html_url: str
    kind: str = "Comment"
    color: int | None = None

    @field_validator("body", mode="before")
    @classmethod
    def _truncate_body(cls, value: object) -> str:
        if not (isinstance(value, str) or value is None):
            msg = "`body` must be a string or None"
            raise ValueError(msg)
        return truncate(value or "", 4096)
