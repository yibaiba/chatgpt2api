from __future__ import annotations

import uvicorn
from services.api import create_app
from services.config import config

app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, access_log=False, log_level="info")