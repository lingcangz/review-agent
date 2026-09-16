"""Per-user state, deliberately outside the repository being reviewed."""

import json
import os
import stat
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class HistoryEntry:
    review_id: str
    base: str
    status: str
    created_at: str


@dataclass
class CliConfig:
    api_url: str = "http://localhost:8000"
    token: str | None = None
    history: list[HistoryEntry] = field(default_factory=list)


def config_path() -> Path:
    override = os.getenv("REVIEW_AGENT_CONFIG")
    if override:
        return Path(override)
    if os.name == "nt":
        root = Path(os.getenv("APPDATA", str(Path.home())))
    else:
        root = Path(os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return root / "review-agent" / "config.json"


def load_config(path: Path | None = None) -> CliConfig:
    target = path or config_path()
    if not target.is_file():
        return CliConfig()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        history = [HistoryEntry(**entry) for entry in raw.get("history", [])]
        return CliConfig(
            api_url=str(raw.get("api_url", "http://localhost:8000")),
            token=raw.get("token"),
            history=history,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("CLI 配置无效；请重新运行 review-agent init 或 login") from None


def save_config(config: CliConfig, path: Path | None = None) -> None:
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(asdict(config), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if os.name != "nt":
        target.chmod(stat.S_IRUSR | stat.S_IWUSR)


def remember_review(config: CliConfig, review_id: str, base: str, status: str) -> None:
    config.history = [entry for entry in config.history if entry.review_id != review_id]
    config.history.insert(
        0,
        HistoryEntry(review_id, base, status, datetime.now(UTC).isoformat()),
    )
    del config.history[50:]
