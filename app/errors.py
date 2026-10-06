"""Stable, positioned API errors."""


class ApiError(Exception):
    """An error that maps directly onto the public error response body.

    The ``code`` is part of the API contract and must stay stable; clients
    match on it. ``position`` points at the offending element so callers can
    localise the problem without parsing the human readable message.
    """

    def __init__(self, code, message, position=None, status=422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.position = position or {}
        self.status = status

    def to_body(self):
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "position": self.position,
            }
        }
