import json
from pathlib import Path

from reimbursement.main import app

Path("openapi.json").write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2), encoding="utf-8")
