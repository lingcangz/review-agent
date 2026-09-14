# Infrastructure

使用 `docker compose -f infra/docker-compose.yml up -d` 启动本地 PostgreSQL 与 Redis。v1 骨架尚未写入业务数据；后续持久化必须通过 SQLAlchemy 与 Alembic，并以 PostgreSQL 为事实来源。
