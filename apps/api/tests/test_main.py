import asyncio
import json
from pathlib import Path
from typing import cast

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from review_agent_api.db_models import Base
from review_agent_api.main import create_app
from review_agent_api.models import ContextRequest, Finding, ReviewModelResult
from review_agent_api.worker import changed_lines, run_model, run_review, verified_findings


class MemoryQueue:
    def __init__(self) -> None:
        self.review_ids: list[str] = []

    async def enqueue(self, review_id: str) -> None:
        self.review_ids.append(review_id)


class MemoryMailer:
    def __init__(self) -> None:
        self.tokens: dict[str, str] = {}
        self.organization_ids: dict[str, str] = {}

    def send_login(self, email: str, token: str, organization_id: str) -> None:
        self.tokens[email] = token
        self.organization_ids[email] = organization_id


def make_client(tmp_path: Path) -> TestClient:
    mailbox = MemoryMailer()
    queue = MemoryQueue()
    app = create_app(f"sqlite:///{tmp_path / 'api.db'}", queue=queue, mailer=mailbox)
    app.state.test_mailbox = mailbox
    app.state.test_queue = queue
    app.state.test_database_url = f"sqlite:///{tmp_path / 'api.db'}"
    Base.metadata.create_all(app.state.database.engine)
    return TestClient(app)


def create_organization(client: TestClient, name: str, email: str) -> dict[str, str]:
    response = client.post("/v1/organizations", json={"name": name, "owner_email": email})
    assert response.status_code == 201
    return response.json()


def login(client: TestClient, email: str, organization_id: str) -> str:
    requested = client.post(
        "/v1/auth/email-login",
        json={"email": email, "organization_id": organization_id},
    )
    assert requested.status_code == 200
    assert "login_token" not in requested.json()
    mailbox = cast(MemoryMailer, client.app.state.test_mailbox)
    token = mailbox.tokens[email]
    assert mailbox.organization_ids[email] == organization_id
    verified = client.post(
        "/v1/auth/email-login/verify",
        json={"email": email, "token": token, "organization_id": organization_id},
    )
    assert verified.status_code == 200
    assert "HttpOnly" in verified.headers["set-cookie"]
    return verified.json()["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_review_requires_authentication_and_valid_context(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    missing_auth = client.post("/v1/reviews", json={"diff": "diff --git a/a.py b/a.py"})
    assert missing_auth.status_code == 401

    organization = create_organization(client, "acme", "owner@acme.example")
    token = login(client, "owner@acme.example", organization["id"])
    invalid_path = client.post(
        "/v1/reviews",
        headers=auth(token),
        json={
            "diff": "diff --git a/a.py b/a.py",
            "context": [{"path": "../.env", "start_line": 1, "end_line": 1, "content": "x"}],
        },
    )
    assert invalid_path.status_code == 422


def test_login_request_requires_an_organization_and_allows_local_web_origin(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    missing_organization = client.post("/v1/auth/email-login", json={"email": "owner@acme.example"})
    assert missing_organization.status_code == 422
    preflight = client.options(
        "/v1/auth/email-login",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert preflight.headers["access-control-allow-credentials"] == "true"


def test_organization_scope_hides_reviews_and_rules(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    first = create_organization(client, "first", "owner@first.example")
    second = create_organization(client, "second", "owner@second.example")
    first_token = login(client, "owner@first.example", first["id"])
    second_token = login(client, "owner@second.example", second["id"])

    review = client.post(
        "/v1/reviews", headers=auth(first_token), json={"diff": "diff --git a/a.py b/a.py\n+pass"}
    )
    assert review.status_code == 202
    assert review.json()["status"] == "queued"
    queue = cast(MemoryQueue, client.app.state.test_queue)
    assert queue.review_ids == [review.json()["review_id"]]
    assert (
        client.get(
            f"/v1/reviews/{review.json()['review_id']}", headers=auth(second_token)
        ).status_code
        == 404
    )

    created_rule = client.post(
        "/v1/review-rules",
        headers=auth(first_token),
        json={"name": "Python", "instruction": "只检查可证实的问题"},
    )
    assert created_rule.status_code == 201
    assert (
        client.patch(
            f"/v1/review-rules/{created_rule.json()['id']}",
            headers=auth(second_token),
            json={"enabled": False},
        ).status_code
        == 404
    )
    assert client.get("/v1/review-rules", headers=auth(second_token)).json() == []


def test_pat_and_context_are_scoped_to_its_organization(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    organization = create_organization(client, "pat-org", "owner@pat.example")
    session_token = login(client, "owner@pat.example", organization["id"])
    pat = client.post(
        "/v1/auth/personal-access-tokens", headers=auth(session_token), json={"name": "local CLI"}
    )
    assert pat.status_code == 200
    review = client.post(
        "/v1/reviews", headers=auth(pat.json()["token"]), json={"diff": "diff --git a/a.py b/a.py"}
    )
    assert review.status_code == 202
    assert client.get(f"/v1/reviews/{review.json()['review_id']}").status_code == 200
    context = client.post(
        f"/v1/reviews/{review.json()['review_id']}/context",
        headers=auth(pat.json()["token"]),
        json={
            "context": [
                {"path": "a.py", "start_line": 1, "end_line": 1, "content": "print('safe')"}
            ]
        },
    )
    assert context.status_code == 200


def test_history_is_organization_scoped_and_context_ranges_are_preserved(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    first = create_organization(client, "history-first", "history-first@example.com")
    second = create_organization(client, "history-second", "history-second@example.com")
    first_token = login(client, "history-first@example.com", first["id"])
    second_token = login(client, "history-second@example.com", second["id"])
    first_review = client.post(
        "/v1/reviews", headers=auth(first_token), json={"diff": "diff --git a/a.py b/a.py"}
    )
    assert first_review.status_code == 202
    second_first_review = client.post(
        "/v1/reviews", headers=auth(first_token), json={"diff": "diff --git a/c.py b/c.py"}
    )
    assert second_first_review.status_code == 202
    second_review = client.post(
        "/v1/reviews", headers=auth(second_token), json={"diff": "diff --git a/b.py b/b.py"}
    )
    assert second_review.status_code == 202

    context = client.post(
        f"/v1/reviews/{first_review.json()['review_id']}/context",
        headers=auth(first_token),
        json={
            "context": [
                {"path": "a.py", "start_line": 1, "end_line": 2, "content": "one\ntwo\n"},
                {"path": "a.py", "start_line": 10, "end_line": 11, "content": "ten\neleven\n"},
            ]
        },
    )
    assert context.status_code == 200
    history = client.get("/v1/reviews?limit=1", headers=auth(first_token))
    assert history.status_code == 200
    assert len(history.json()["items"]) == 1
    cursor = history.json()["next_cursor"]
    assert cursor is not None
    next_page = client.get(f"/v1/reviews?limit=1&cursor={cursor}", headers=auth(first_token))
    assert next_page.status_code == 200
    assert {
        history.json()["items"][0]["review_id"],
        next_page.json()["items"][0]["review_id"],
    } == {first_review.json()["review_id"], second_first_review.json()["review_id"]}
    assert (
        client.get(
            f"/v1/reviews?cursor={second_review.json()['review_id']}", headers=auth(first_token)
        ).status_code
        == 400
    )


def test_worker_persists_bounded_context_request(tmp_path: Path, monkeypatch) -> None:
    client = make_client(tmp_path)
    organization = create_organization(client, "context-range", "context-range@example.com")
    token = login(client, "context-range@example.com", organization["id"])
    submitted = client.post(
        "/v1/reviews", headers=auth(token), json={"diff": "diff --git a/a.py b/a.py"}
    )

    async def fake_model(*_args) -> ReviewModelResult:
        return ReviewModelResult(
            status="needs_context",
            report="需要查看有限范围。",
            findings=[],
            requested_context=[ContextRequest(path="a.py", start_line=10, end_line=20)],
        )

    monkeypatch.setattr("review_agent_api.worker.run_model", fake_model)
    asyncio.run(
        run_review(
            {"database_url": client.app.state.test_database_url}, submitted.json()["review_id"]
        )
    )
    result = client.get(f"/v1/reviews/{submitted.json()['review_id']}", headers=auth(token))
    assert result.json()["requested_context"] == [
        {"path": "a.py", "start_line": 10, "end_line": 20}
    ]


def test_admin_invitation_creates_a_member_who_can_start_a_session(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    organization = create_organization(client, "invitation-org", "owner@invite.example")
    owner_token = login(client, "owner@invite.example", organization["id"])
    invitation = client.post(
        "/v1/invitations",
        headers=auth(owner_token),
        json={"email": "member@invite.example", "role": "member"},
    )
    assert invitation.status_code == 201
    accepted = client.post(
        "/v1/invitations/accept",
        json={"code": invitation.json()["code"], "email": "member@invite.example"},
    )
    assert accepted.status_code == 204
    assert login(client, "member@invite.example", organization["id"])


def test_initial_alembic_migration_creates_persistent_models(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    database_file = tmp_path / "migrated.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_file}")
    command.upgrade(config, "head")

    from sqlalchemy import create_engine

    inspector = inspect(create_engine(f"sqlite:///{database_file}"))
    tables = set(inspector.get_table_names())
    assert {
        "organizations",
        "memberships",
        "sessions",
        "personal_access_tokens",
        "reviews",
        "review_rules",
        "review_findings",
    } <= tables
    assert {"static_analysis"} <= {column["name"] for column in inspector.get_columns("reviews")}
    assert {"confidence", "category"} <= {
        column["name"] for column in inspector.get_columns("review_findings")
    }


def test_worker_only_accepts_findings_anchored_to_changed_lines() -> None:
    diff = "@@ -1,1 +5,2 @@\n-old\n+new\n+next\n"
    finding = Finding(
        severity="P1",
        confidence="high",
        category="correctness",
        path="src/service.py",
        start_line=5,
        end_line=6,
        title="错误处理丢失",
        evidence="new 新增后直接返回。",
        recommendation="补充异常处理。",
    )
    unanchored = finding.model_copy(update={"start_line": 4, "end_line": 5})

    assert changed_lines("+++ b/src/service.py\n" + diff) == {"src/service.py": {5, 6}}
    assert verified_findings([finding, unanchored], "+++ b/src/service.py\n" + diff) == [finding]


def test_worker_persists_validated_structured_result(tmp_path: Path, monkeypatch) -> None:
    client = make_client(tmp_path)
    organization = create_organization(client, "worker-org", "owner@worker.example")
    token = login(client, "owner@worker.example", organization["id"])
    submitted = client.post(
        "/v1/reviews",
        headers=auth(token),
        json={"diff": "+++ b/src/service.py\n@@ -1 +5 @@\n-old\n+new"},
    )

    async def fake_model(*_args) -> ReviewModelResult:
        return ReviewModelResult(
            status="completed",
            report="发现一个可确认的问题。",
            findings=[
                Finding(
                    severity="P1",
                    confidence="high",
                    category="correctness",
                    path="src/service.py",
                    start_line=5,
                    end_line=5,
                    title="返回值错误",
                    evidence="新增的 new 直接作为返回值。",
                    recommendation="恢复预期返回值。",
                )
            ],
            requested_context=[],
        )

    monkeypatch.setattr("review_agent_api.worker.run_model", fake_model)
    asyncio.run(
        run_review(
            {"database_url": client.app.state.test_database_url}, submitted.json()["review_id"]
        )
    )
    result = client.get(f"/v1/reviews/{submitted.json()['review_id']}", headers=auth(token))
    assert result.json()["status"] == "completed"
    assert result.json()["findings"][0]["path"] == "src/service.py"


def test_worker_uses_configured_openai_base_url(monkeypatch) -> None:
    configured: dict[str, object] = {}

    class FakeResponses:
        async def create(self, **_kwargs):
            return type(
                "FakeResponse",
                (),
                {
                    "output_text": json.dumps(
                        {
                            "status": "completed",
                            "report": "未发现可确认问题。",
                            "findings": [],
                            "requested_context": [],
                        }
                    )
                },
            )()

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            configured.update(kwargs)
            self.responses = FakeResponses()

        async def close(self) -> None:
            return None

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example/v1")
    monkeypatch.setattr("review_agent_api.worker.AsyncOpenAI", FakeClient)

    result = asyncio.run(run_model("diff --git a/a.py b/a.py", [], []))

    assert result.status == "completed"
    assert configured["base_url"] == "https://gateway.example/v1"
