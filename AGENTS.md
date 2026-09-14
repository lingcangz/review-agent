# Team Autonomous Code Review Agent

## Product outcome

Build a team product that reviews Python Git changes autonomously.
The first release accepts a local Git diff plus minimal requested context, produces a Chinese review report, and never blocks a merge or writes to the reviewed repository.

Prioritize only:
1. correctness defects;
2. security vulnerabilities;
3. regressions caused directly by the change.

Do not report style preferences, speculative refactors, or low-confidence concerns.

## Architecture

- Python 3.12 with uv: FastAPI API, arq worker, Pydantic v2, SQLAlchemy 2, Alembic.
- Next.js App Router with TypeScript for the dashboard.
- PostgreSQL is the source of truth; Redis is only for jobs and ephemeral coordination.
- OpenAI Responses API produces structured findings validated by Pydantic.
- CLI code must run on Windows, macOS, and Linux.
- The API never requires a complete repository archive.

## Security and privacy

- Never log source code, diffs, prompts, API keys, tokens, cookies, or email magic-link tokens.
- Redact secrets before an API request and reject files matched by `.review-agentignore`.
- Send only the diff and explicitly requested, path-scoped context to the cloud or model.
- Enforce organization isolation in every query and object-storage key.
- Store raw code context for at most 30 days; retain findings and audit metadata separately.
- Use environment variables for secrets. Commit only `.env.example`.

## Review behavior

- Every finding must identify an exact changed path and line range.
- Every finding must include concrete evidence from the submitted change or requested context.
- Use P0 only for exploitable critical risk, P1 for likely defects/security issues, and P2 for confirmed lower-impact defects.
- If evidence is insufficient, request bounded context or emit no finding.
- Findings are advisory in v1. Do not create commits, modify user code, comment on pull requests, or change CI status.

## Engineering rules

- Inspect existing code and active instructions before changing files.
- Make the smallest coherent change that satisfies the requested outcome.
- Add or update tests for behavior changes; do not add tests that merely mirror implementation details.
- Run focused checks first, then the relevant full suite before declaring work complete.
- Use Alembic for every persistent schema change. Do not edit an applied migration.
- Keep API request/response models typed and document public endpoints in OpenAPI.
- Generate TypeScript API types from OpenAPI; do not duplicate backend contracts manually.
- Keep user-visible product copy and generated review reports in Chinese.

## Completion standard

Before completion, report:
1. changed behavior and files;
2. commands run and their results;
3. remaining risks or intentionally deferred work.

Do not claim a task is complete when tests, migrations, type checks, or security-sensitive behavior remain unverified.
```