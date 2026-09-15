from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


def validate_relative_path(value: str) -> str:
    """Accept only normalized, repository-relative POSIX paths."""
    if not value or value.startswith("/") or "\\" in value:
        raise ValueError("路径必须是相对仓库路径")
    segments = value.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ValueError("路径必须是规范的相对路径")
    return value


class RequestedContext(BaseModel):
    path: str = Field(description="仓库相对路径")
    content: str = Field(min_length=1, max_length=100_000, description="已脱敏的文件内容")

    @field_validator("path")
    @classmethod
    def path_is_relative(cls, value: str) -> str:
        return validate_relative_path(value)


class ReviewRequest(BaseModel):
    """Diff and explicitly supplied, path-scoped context only."""

    diff: str = Field(min_length=1, max_length=500_000)
    context: list[RequestedContext] = Field(default_factory=list, max_length=20)


class ContextUploadRequest(BaseModel):
    context: list[RequestedContext] = Field(min_length=1, max_length=20)


class Finding(BaseModel):
    severity: Literal["P0", "P1", "P2"]
    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    title: str
    evidence: str
    recommendation: str

    @field_validator("path")
    @classmethod
    def path_is_relative(cls, value: str) -> str:
        return validate_relative_path(value)

    @model_validator(mode="after")
    def valid_range(self) -> "Finding":
        if self.end_line < self.start_line:
            raise ValueError("结束行不能小于开始行")
        return self


class ReviewResponse(BaseModel):
    review_id: str
    status: Literal["queued", "running", "completed", "needs_context", "failed"]
    report: str | None = None
    findings: list[Finding] = Field(default_factory=list)
    requested_context_paths: list[str] = Field(default_factory=list)


class ReviewModelResult(BaseModel):
    """The complete model output before it is verified against the submitted diff."""

    status: Literal["completed", "needs_context"]
    report: str = Field(min_length=1, max_length=10_000)
    findings: list[Finding] = Field(max_length=50)
    requested_context_paths: list[str] = Field(max_length=20)

    @field_validator("requested_context_paths")
    @classmethod
    def paths_are_relative(cls, values: list[str]) -> list[str]:
        return [validate_relative_path(value) for value in values]


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    owner_email: EmailStr


class OrganizationResponse(BaseModel):
    id: str
    name: str


class InvitationCreate(BaseModel):
    email: EmailStr
    role: Literal["admin", "member"] = "member"


class InvitationResponse(BaseModel):
    invitation_id: str
    code: str = Field(description="仅在创建时返回；应通过安全渠道传递。")
    expires_at: datetime


class InvitationAccept(BaseModel):
    code: str = Field(min_length=20, max_length=200)
    email: EmailStr


class EmailLoginRequest(BaseModel):
    email: EmailStr
    organization_id: str = Field(min_length=1, max_length=36)


class EmailLoginResponse(BaseModel):
    message: str


class EmailLoginVerify(BaseModel):
    email: EmailStr
    token: str = Field(min_length=20, max_length=200)
    organization_id: str = Field(min_length=1, max_length=36)


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime


class PersonalAccessTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    expires_in_days: int | None = Field(default=90, ge=1, le=365)


class PersonalAccessTokenResponse(BaseModel):
    id: str
    name: str
    token: str = Field(description="仅在创建时返回，请立即保存。")
    expires_at: datetime | None


class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    instruction: str = Field(min_length=1, max_length=10_000)
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=10_000)


class RuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    instruction: str | None = Field(default=None, min_length=1, max_length=10_000)
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=10_000)


class RuleResponse(RuleCreate):
    id: str
