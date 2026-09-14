from uuid import uuid4

from fastapi import FastAPI

from review_agent_api.models import ReviewRequest, ReviewResponse

app = FastAPI(
    title="Review Agent API",
    version="0.1.0",
    description="只接收 Git diff 与明确请求的按路径上下文的审阅 API。",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/reviews", response_model=ReviewResponse)
def create_review(request: ReviewRequest) -> ReviewResponse:
    """Accept a bounded request without persisting or logging source code."""
    return ReviewResponse(
        review_id=str(uuid4()),
        status="completed",
        report="已接收变更 diff。当前 v1 骨架不会上传完整仓库，也不会阻断合并；尚未发现可确认的问题。",
        findings=[],
    )
