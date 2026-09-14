from typing import Literal

from pydantic import BaseModel, Field, field_validator


def validate_relative_path(value: str) -> str:
    """Accept only normalized, repository-relative paths."""
    if not value or value.startswith("/") or "\\" in value:
        raise ValueError("路径必须是相对仓库路径")
    segments = value.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ValueError("路径必须是规范的相对路径")
    return value


class RequestedContext(BaseModel):
    """A single file explicitly requested by the reviewer."""

    path: str = Field(description="仓库相对路径")
    content: str = Field(min_length=1, max_length=100_000, description="已脱敏的文件内容")

    @field_validator("path")
    @classmethod
    def path_is_relative(cls, value: str) -> str:
        return validate_relative_path(value)


class ReviewRequest(BaseModel):
    """The complete v1 review input: a diff and bounded optional context."""

    organization_id: str = Field(min_length=1, max_length=100)
    diff: str = Field(min_length=1, max_length=500_000)
    context: list[RequestedContext] = Field(default_factory=list, max_length=20)


class Finding(BaseModel):
    """An advisory issue anchored to changed lines."""

    severity: Literal["P0", "P1", "P2"]
    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    title: str
    evidence: str
    recommendation: str


class ReviewResponse(BaseModel):
    review_id: str
    status: Literal["completed", "needs_context"]
    report: str
    findings: list[Finding] = Field(default_factory=list)
    requested_context_paths: list[str] = Field(default_factory=list)
