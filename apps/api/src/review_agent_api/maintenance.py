"""Scheduled maintenance commands; they never print source material."""

from datetime import UTC, datetime

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from review_agent_api.db_models import Review, ReviewContext


def purge_expired_raw_content(session: Session) -> None:
    """Delete path-scoped raw context and redact expired diffs, retaining audit metadata."""
    current_time = datetime.now(UTC)
    session.execute(
        delete(ReviewContext).where(ReviewContext.raw_content_expires_at <= current_time)
    )
    session.execute(
        update(Review).where(Review.raw_content_expires_at <= current_time).values(diff="")
    )


def main() -> int:
    from review_agent_api.database import Database

    database = Database()
    with database.sessions() as session:
        purge_expired_raw_content(session)
        session.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
