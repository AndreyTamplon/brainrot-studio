import re
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from .speech import validate_decimal_speech


class JobRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=800)
    background_id: str
    speaker_ids: list[str] = Field(min_length=1, max_length=3)
    subtitles: bool = True
    instructions: str = Field(default="", max_length=2500)
    language: Literal["ru", "en"] = "ru"
    duration: int = Field(default=45, ge=15, le=90)
    budget: float = Field(default=1.5, gt=0, le=3)

    @model_validator(mode="after")
    def unique_speakers(self):
        if len(set(self.speaker_ids)) != len(self.speaker_ids):
            raise ValueError("Участники не должны повторяться")
        return self


class Source(BaseModel):
    title: str
    url: str
    note: str = ""

    @field_validator("url")
    @classmethod
    def public_link(cls, value):
        parsed = urlparse(value)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username:
            raise ValueError("Source must be an HTTP(S) URL")
        return value


class Research(BaseModel):
    summary: str
    facts: list[str] = Field(min_length=2, max_length=10)
    sources: list[Source] = Field(min_length=1, max_length=10)
    caveats: list[str] = []


class Scene(BaseModel):
    id: str = Field(pattern=r"^s[0-9]{1,2}$")
    speaker_id: str
    text: str = Field(min_length=1, max_length=650)
    visual_query: str = Field(default="", max_length=160)
    visual_caption: str = Field(default="", max_length=120)

    @field_validator("visual_caption")
    @classmethod
    def audience_caption(cls, value):
        if re.search(
            r"file:|\d+[.:]\d{2,3}\s*[–-]|вставка\s+(?:один|два|\d)", value, re.IGNORECASE
        ):
            raise ValueError("On-screen captions must not contain production notes or timecodes")
        return value

    @field_validator("text")
    @classmethod
    def speech_only(cls, value):
        if re.match(r"\s*\[[^\]]+\]", value):
            raise ValueError("Spoken text must not start with speaker labels or stage directions")
        return validate_decimal_speech(value.strip())


class Script(BaseModel):
    title: str = Field(max_length=100)
    hook: str = Field(max_length=250)
    scenes: list[Scene] = Field(min_length=2, max_length=12)

    @model_validator(mode="after")
    def unique_scenes(self):
        if len({s.id for s in self.scenes}) != len(self.scenes):
            raise ValueError("Scene IDs must be unique")
        return self


class RenderPlan(BaseModel):
    layout: Literal["overlay", "split"] = "overlay"
    caption_color: Literal["yellow", "white", "mint"] = "yellow"
    caption_size: int = Field(default=76, ge=56, le=94)
    character_size: int = Field(default=530, ge=360, le=650)
    image_seconds: float = Field(default=4.5, ge=2, le=10)
    playback_speed: float = Field(default=1.0, ge=0.85, le=1.25)


class Review(BaseModel):
    passed: bool
    summary: str
    issues: list[str] = []
    suggested_plan: RenderPlan | None = None


class ScriptReview(BaseModel):
    passed: bool
    issues: list[str] = []


class EvidenceReview(BaseModel):
    passed: bool
    issues: list[Annotated[str, Field(max_length=240)]] = Field(default_factory=list, max_length=5)


class Revision(BaseModel):
    instructions: str = Field(min_length=3, max_length=2000)
    subtitles: bool | None = None
    background_id: str | None = None
