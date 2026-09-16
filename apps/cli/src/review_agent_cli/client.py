"""Small stdlib HTTP client; errors intentionally omit request bodies and tokens."""

import json
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class ApiClient:
    def __init__(self, api_url: str, token: str | None = None) -> None:
        self.api_url = api_url.rstrip("/")
        self.token = token

    def request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        data = None
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        request = Request(f"{self.api_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise ValueError(f"API 请求失败（HTTP {error.code}）") from error
        if not isinstance(body, dict):
            raise ValueError("服务返回了无效响应")
        return body
