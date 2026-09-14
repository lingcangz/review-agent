"""Write the FastAPI-generated public OpenAPI schema for web type generation."""

import json
from pathlib import Path

from review_agent_api.main import app

output = Path(__file__).parents[1] / "openapi.json"
output.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
