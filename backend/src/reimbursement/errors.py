from typing import Any


class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 422, details: Any = None):
        self.code, self.message, self.status = code, message, status
        self.details = details or []
