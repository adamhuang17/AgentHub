from __future__ import annotations


class NotFoundError(Exception):
    pass


class ValidationError(Exception):
    def __init__(self, message: str, *, code: str = "validation_error") -> None:
        super().__init__(message)
        self.code = code
