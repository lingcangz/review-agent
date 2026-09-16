from review_agent_cli.safety import changed_paths, is_ignored, redact_secrets


def test_redact_secrets_removes_common_tokens() -> None:
    content = "OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz\nTOKEN=private"

    assert "abcdefghijklmnopqrstuvwxyz" not in redact_secrets(content)
    assert "private" not in redact_secrets(content)


def test_ignored_paths_are_rejected() -> None:
    assert is_ignored("secrets/production.env", ["secrets/**"])
    assert is_ignored("deploy.key", ["*.key"])


def test_changed_paths_reads_added_diff_files() -> None:
    diff = "--- a/src/a.py\n+++ b/src/a.py\n+print('changed')"

    assert changed_paths(diff) == ["src/a.py"]


def test_changed_paths_includes_deleted_file() -> None:
    diff = "--- a/src/removed.py\n+++ /dev/null\n-old"

    assert changed_paths(diff) == ["src/removed.py"]
