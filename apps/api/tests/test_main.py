import pytest
from pydantic import ValidationError

from review_agent_api.main import create_review, health
from review_agent_api.models import ReviewRequest


def test_health_is_available() -> None:
    response = health()

    assert response == {"status": "ok"}


def test_review_accepts_diff_and_bounded_context() -> None:
    response = create_review(
        ReviewRequest(
            organization_id="acme",
            diff="diff --git a/app.py b/app.py\n+new file mode 100644",
            context=[{"path": "src/app.py", "content": "print('safe')"}],
        )
    )

    assert response.status == "completed"
    assert response.findings == []
    assert "完整仓库" in response.report


def test_review_rejects_non_relative_context_path() -> None:
    with pytest.raises(ValidationError):
        ReviewRequest(
            organization_id="acme",
            diff="diff --git a/app.py b/app.py",
            context=[{"path": "../.env", "content": "TOKEN=value"}],
        )
