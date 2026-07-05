class NotFoundError(Exception):
    def __init__(self, resource: str, resource_id: str | int):
        self.resource = resource
        self.resource_id = resource_id
        super().__init__(f"{resource} with id '{resource_id}' not found")


class AuthenticationError(Exception):
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message)


class AuthorizationError(Exception):
    def __init__(self, message: str = "Insufficient permissions"):
        super().__init__(message)


class ConflictError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


class ValidationError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


class InsufficientCreditsError(Exception):
    def __init__(self, message: str = "크레딧이 부족합니다. 관리자에게 문의하세요."):
        super().__init__(message)
