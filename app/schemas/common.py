from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginationMeta(BaseModel):
    total: int
    page: int
    limit: int
    pages: int


class APIResponse(BaseModel, Generic[T]):
    success: bool
    data: T | None = None
    error: str | None = None
    metadata: PaginationMeta | None = None

    @classmethod
    def ok(cls, data: T, metadata: PaginationMeta | None = None) -> "APIResponse[T]":
        return cls(success=True, data=data, metadata=metadata)

    @classmethod
    def fail(cls, error: str) -> "APIResponse[None]":
        return cls(success=False, data=None, error=error)
