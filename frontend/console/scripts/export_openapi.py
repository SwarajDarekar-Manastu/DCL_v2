"""Print the backend's OpenAPI schema (DCL_ROLE=api) as JSON; input of `npm run gen:api`.

Run from the repository root: `uv run python frontend/console/scripts/export_openapi.py`.
"""

import json
import os
import sys

os.environ.setdefault("DCL_ROLE", "api")
os.environ.setdefault("DCL_ENV", "dev")
sys.path.insert(0, os.getcwd())

from backend.main import create_app  # noqa: E402

json.dump(create_app().openapi(), sys.stdout, indent=1, sort_keys=True)
