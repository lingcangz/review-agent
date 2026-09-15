"""Organization-isolated HTTP API. Request bodies are intentionally never logged."""

from datetime import UTC, datetime, timedelta
from os import getenv
from typing import Annotated, Any, Literal, cast

from collections.abc import Generator

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from review_agent_api.database import Database
from review_agent_api.db_models import (
    EmailLoginToken,
    Invitation,
    Membership,
    Organization,
    PersonalAccessToken,
    Review,
    ReviewContext,
    ReviewFinding,
    ReviewRule,
    SessionToken,
    User,
)
from review_agent_api.models import (
    AuthTokenResponse,
    ContextUploadRequest,
    EmailLoginRequest,
    EmailLoginResponse,
    EmailLoginVerify,
    Finding,
    InvitationAccept,
    InvitationCreate,
    InvitationResponse,
    OrganizationCreate,
    OrganizationResponse,
    PersonalAccessTokenCreate,
    PersonalAccessTokenResponse,
    ReviewRequest,
    ReviewResponse,
    RuleCreate,
    RuleResponse,
    RuleUpdate,
)
from review_agent_api.mailer import SmtpMailer
from review_agent_api.queue import ArqReviewQueue, ReviewQueue
from review_agent_api.security import new_token, token_hash

bearer_scheme = HTTPBearer(auto_error=False)
RAW_CONTENT_RETENTION = timedelta(days=30)
SESSION_LIFETIME = timedelta(days=7)
LOGIN_LIFETIME = timedelta(minutes=15)
INVITATION_LIFETIME = timedelta(days=7)


class Principal:
    def __init__(self, organization_id: str, user_id: str, role: str) -> None:
        self.organization_id = organization_id
        self.user_id = user_id
        self.role = role


def now() -> datetime:
    return datetime.now(UTC)


def is_expired(value: datetime | None) -> bool:
    if value is None:
        return False
    return value.replace(tzinfo=UTC) <= now() if value.tzinfo is None else value <= now()


def review_response(review: Review, session: Session) -> ReviewResponse:
    findings = session.scalars(
        select(ReviewFinding).where(
            ReviewFinding.review_id == review.id,
            ReviewFinding.organization_id == review.organization_id,
        )
    ).all()
    return ReviewResponse(
        review_id=review.id,
        status=cast(
            Literal["queued", "running", "completed", "needs_context", "failed"], review.status
        ),
        report=review.report,
        findings=[Finding.model_validate(finding, from_attributes=True) for finding in findings],
        requested_context_paths=review.requested_context_paths,
    )


def create_app(
    database_url: str | None = None,
    queue: ReviewQueue | None = None,
    mailer: Any | None = None,
) -> FastAPI:
    database = Database(database_url)
    review_queue = queue or ArqReviewQueue()
    login_mailer = mailer or SmtpMailer()
    app = FastAPI(
        title="Review Agent API",
        version="0.2.0",
        description="组织隔离的 Git diff 审阅 API；只接收 diff 与明确指定的最小上下文。",
    )
    cors_origins = [
        origin.strip()
        for origin in getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.state.database = database

    def get_session() -> Generator[Session, None, None]:
        yield from database.session()

    DbSession = Annotated[Session, Depends(get_session)]

    def current_principal(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
        session: DbSession,
        browser_session: Annotated[str | None, Cookie(alias="review_agent_session")] = None,
    ) -> Principal:
        # Opportunistic cleanup complements the scheduled command without emitting raw content.
        from review_agent_api.maintenance import purge_expired_raw_content

        purge_expired_raw_content(session)
        session.commit()
        token = (
            credentials.credentials
            if credentials and credentials.scheme.lower() == "bearer"
            else browser_session
        )
        if token is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="需要 Bearer 凭据")
        digest = token_hash(token)
        active_session = session.scalar(
            select(SessionToken).where(SessionToken.token_hash == digest)
        )
        if (
            active_session
            and active_session.revoked_at is None
            and not is_expired(active_session.expires_at)
        ):
            membership = session.scalar(
                select(Membership).where(
                    Membership.organization_id == active_session.organization_id,
                    Membership.user_id == active_session.user_id,
                )
            )
            if membership:
                return Principal(membership.organization_id, membership.user_id, membership.role)
        pat = session.scalar(
            select(PersonalAccessToken).where(PersonalAccessToken.token_hash == digest)
        )
        if pat and pat.revoked_at is None and not is_expired(pat.expires_at):
            membership = session.scalar(
                select(Membership).where(
                    Membership.organization_id == pat.organization_id,
                    Membership.user_id == pat.user_id,
                )
            )
            if membership:
                return Principal(membership.organization_id, membership.user_id, membership.role)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="凭据无效或已过期")

    CurrentPrincipal = Annotated[Principal, Depends(current_principal)]

    def require_admin(principal: CurrentPrincipal) -> Principal:
        if principal.role != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
        return principal

    AdminPrincipal = Annotated[Principal, Depends(require_admin)]

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/v1/organizations",
        response_model=OrganizationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_organization(
        payload: OrganizationCreate, session: DbSession
    ) -> OrganizationResponse:
        email = str(payload.owner_email).lower()
        user = session.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email)
            session.add(user)
            session.flush()
        organization = Organization(name=payload.name)
        session.add(organization)
        session.flush()
        session.add(Membership(organization_id=organization.id, user_id=user.id, role="admin"))
        try:
            session.commit()
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(status_code=409, detail="组织名称已存在") from error
        return OrganizationResponse(id=organization.id, name=organization.name)

    @app.post(
        "/v1/invitations", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED
    )
    def create_invitation(
        payload: InvitationCreate, principal: AdminPrincipal, session: DbSession
    ) -> InvitationResponse:
        code = new_token("rai")
        invitation = Invitation(
            organization_id=principal.organization_id,
            email=str(payload.email).lower(),
            role=payload.role,
            code_hash=token_hash(code),
            expires_at=now() + INVITATION_LIFETIME,
        )
        session.add(invitation)
        session.commit()
        return InvitationResponse(
            invitation_id=invitation.id, code=code, expires_at=invitation.expires_at
        )

    @app.post("/v1/invitations/accept", status_code=status.HTTP_204_NO_CONTENT)
    def accept_invitation(payload: InvitationAccept, session: DbSession) -> None:
        invitation = session.scalar(
            select(Invitation).where(Invitation.code_hash == token_hash(payload.code))
        )
        if (
            invitation is None
            or invitation.accepted_at is not None
            or is_expired(invitation.expires_at)
        ):
            raise HTTPException(status_code=400, detail="邀请码无效或已过期")
        user = session.scalar(select(User).where(User.email == str(payload.email).lower()))
        if user is None:
            user = User(email=str(payload.email).lower())
            session.add(user)
            session.flush()
        if user.email != invitation.email:
            raise HTTPException(status_code=403, detail="邀请码与邮箱不匹配")
        exists = session.scalar(
            select(Membership).where(
                Membership.organization_id == invitation.organization_id,
                Membership.user_id == user.id,
            )
        )
        if exists is None:
            session.add(
                Membership(
                    organization_id=invitation.organization_id,
                    user_id=user.id,
                    role=invitation.role,
                )
            )
        invitation.accepted_at = now()
        session.commit()

    @app.post("/v1/auth/email-login", response_model=EmailLoginResponse)
    def request_email_login(payload: EmailLoginRequest, session: DbSession) -> EmailLoginResponse:
        # A production mail sender consumes this record. Keep the response generic to avoid account discovery.
        email = str(payload.email).lower()
        user = session.scalar(select(User).where(User.email == email))
        membership = (
            session.scalar(
                select(Membership).where(
                    Membership.organization_id == payload.organization_id,
                    Membership.user_id == user.id,
                )
            )
            if user
            else None
        )
        if membership is None:
            return EmailLoginResponse(message="如该邮箱可登录，登录链接已发送。")
        token = new_token("ral")
        login = EmailLoginToken(
            organization_id=payload.organization_id,
            email=email,
            token_hash=token_hash(token),
            expires_at=now() + LOGIN_LIFETIME,
        )
        session.add(login)
        session.commit()
        try:
            login_mailer.send_login(email, token, payload.organization_id)
        except OSError as error:
            session.delete(login)
            session.commit()
            raise HTTPException(status_code=503, detail="邮件服务暂不可用") from error
        return EmailLoginResponse(message="如该邮箱可登录，登录链接已发送。")

    @app.post("/v1/auth/email-login/verify", response_model=AuthTokenResponse)
    def verify_email_login(
        payload: EmailLoginVerify, response: Response, session: DbSession
    ) -> AuthTokenResponse:
        email = str(payload.email).lower()
        login = session.scalar(
            select(EmailLoginToken).where(
                EmailLoginToken.email == email,
                EmailLoginToken.token_hash == token_hash(payload.token),
                EmailLoginToken.organization_id == payload.organization_id,
            )
        )
        if login is None or login.consumed_at is not None or is_expired(login.expires_at):
            raise HTTPException(status_code=401, detail="登录链接无效或已过期")
        user = session.scalar(select(User).where(User.email == email))
        if user is None:
            raise HTTPException(status_code=403, detail="该邮箱不是此组织成员")
        membership = session.scalar(
            select(Membership).where(
                Membership.organization_id == payload.organization_id,
                Membership.user_id == user.id,
            )
        )
        if membership is None:
            raise HTTPException(status_code=403, detail="该邮箱不是此组织成员")
        access_token = new_token("ras")
        expires_at = now() + SESSION_LIFETIME
        session.add(
            SessionToken(
                organization_id=membership.organization_id,
                user_id=user.id,
                token_hash=token_hash(access_token),
                expires_at=expires_at,
            )
        )
        login.consumed_at = now()
        session.commit()
        response.set_cookie(
            key="review_agent_session",
            value=access_token,
            httponly=True,
            secure=getenv("APP_ENV", "development") == "production",
            samesite="lax",
            max_age=int(SESSION_LIFETIME.total_seconds()),
            path="/",
        )
        return AuthTokenResponse(access_token=access_token, expires_at=expires_at)

    @app.post("/v1/auth/personal-access-tokens", response_model=PersonalAccessTokenResponse)
    def create_pat(
        payload: PersonalAccessTokenCreate, principal: CurrentPrincipal, session: DbSession
    ) -> PersonalAccessTokenResponse:
        token = new_token("rap")
        expires_at = (
            now() + timedelta(days=payload.expires_in_days)
            if payload.expires_in_days is not None
            else None
        )
        pat = PersonalAccessToken(
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            name=payload.name,
            token_prefix=token[:12],
            token_hash=token_hash(token),
            expires_at=expires_at,
        )
        session.add(pat)
        session.commit()
        return PersonalAccessTokenResponse(
            id=pat.id, name=pat.name, token=token, expires_at=expires_at
        )

    @app.post("/v1/reviews", response_model=ReviewResponse, status_code=status.HTTP_202_ACCEPTED)
    async def create_review(
        payload: ReviewRequest, principal: CurrentPrincipal, session: DbSession
    ) -> ReviewResponse:
        review = Review(
            organization_id=principal.organization_id,
            created_by_user_id=principal.user_id,
            diff=payload.diff,
            raw_content_expires_at=now() + RAW_CONTENT_RETENTION,
            status="queued",
        )
        session.add(review)
        session.flush()
        for item in payload.context:
            session.add(
                ReviewContext(
                    organization_id=principal.organization_id,
                    review_id=review.id,
                    path=item.path,
                    content=item.content,
                    raw_content_expires_at=now() + RAW_CONTENT_RETENTION,
                )
            )
        session.commit()
        try:
            await review_queue.enqueue(review.id)
        except Exception as error:
            review.status = "failed"
            review.report = "审查队列暂不可用，请稍后重新提交。"
            session.commit()
            raise HTTPException(status_code=503, detail="审查队列暂不可用") from error
        return review_response(review, session)

    @app.get("/v1/reviews/{review_id}", response_model=ReviewResponse)
    def get_review(
        review_id: str, principal: CurrentPrincipal, session: DbSession
    ) -> ReviewResponse:
        review = session.scalar(
            select(Review).where(
                Review.id == review_id, Review.organization_id == principal.organization_id
            )
        )
        if review is None:
            raise HTTPException(status_code=404, detail="审查任务不存在")
        return review_response(review, session)

    @app.post("/v1/reviews/{review_id}/context", response_model=ReviewResponse)
    async def upload_context(
        review_id: str,
        payload: ContextUploadRequest,
        principal: CurrentPrincipal,
        session: DbSession,
    ) -> ReviewResponse:
        review = session.scalar(
            select(Review).where(
                Review.id == review_id, Review.organization_id == principal.organization_id
            )
        )
        if review is None:
            raise HTTPException(status_code=404, detail="审查任务不存在")
        for item in payload.context:
            existing = session.scalar(
                select(ReviewContext).where(
                    ReviewContext.review_id == review.id, ReviewContext.path == item.path
                )
            )
            if existing:
                existing.content = item.content
                existing.raw_content_expires_at = now() + RAW_CONTENT_RETENTION
            else:
                session.add(
                    ReviewContext(
                        organization_id=principal.organization_id,
                        review_id=review.id,
                        path=item.path,
                        content=item.content,
                        raw_content_expires_at=now() + RAW_CONTENT_RETENTION,
                    )
                )
        review.status = "queued"
        session.commit()
        try:
            await review_queue.enqueue(review.id)
        except Exception as error:
            review.status = "failed"
            review.report = "审查队列暂不可用，请稍后重新提交。"
            session.commit()
            raise HTTPException(status_code=503, detail="审查队列暂不可用") from error
        return review_response(review, session)

    @app.get("/v1/review-rules", response_model=list[RuleResponse])
    def list_rules(principal: CurrentPrincipal, session: DbSession) -> list[RuleResponse]:
        rules = session.scalars(
            select(ReviewRule)
            .where(ReviewRule.organization_id == principal.organization_id)
            .order_by(ReviewRule.priority, ReviewRule.created_at)
        ).all()
        return [RuleResponse.model_validate(rule, from_attributes=True) for rule in rules]

    @app.post("/v1/review-rules", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
    def create_rule(
        payload: RuleCreate, principal: AdminPrincipal, session: DbSession
    ) -> RuleResponse:
        rule = ReviewRule(organization_id=principal.organization_id, **payload.model_dump())
        session.add(rule)
        session.commit()
        return RuleResponse.model_validate(rule, from_attributes=True)

    @app.patch("/v1/review-rules/{rule_id}", response_model=RuleResponse)
    def update_rule(
        rule_id: str, payload: RuleUpdate, principal: AdminPrincipal, session: DbSession
    ) -> RuleResponse:
        rule = session.scalar(
            select(ReviewRule).where(
                ReviewRule.id == rule_id, ReviewRule.organization_id == principal.organization_id
            )
        )
        if rule is None:
            raise HTTPException(status_code=404, detail="审查规则不存在")
        for name, value in payload.model_dump(exclude_unset=True).items():
            setattr(rule, name, value)
        session.commit()
        return RuleResponse.model_validate(rule, from_attributes=True)

    @app.delete("/v1/review-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_rule(rule_id: str, principal: AdminPrincipal, session: DbSession) -> None:
        rule = session.scalar(
            select(ReviewRule).where(
                ReviewRule.id == rule_id, ReviewRule.organization_id == principal.organization_id
            )
        )
        if rule is None:
            raise HTTPException(status_code=404, detail="审查规则不存在")
        session.delete(rule)
        session.commit()

    return app


app = create_app()
