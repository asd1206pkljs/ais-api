from fastapi import APIRouter, Request

from app.middleware import limiter
from app.schemas.common import APIResponse
from app.schemas.consent import LegalVersions
from app.services.consent_service import ConsentService

router = APIRouter(prefix="/legal", tags=["legal"])


@router.get("/versions", response_model=APIResponse[LegalVersions])
@limiter.limit("60/minute")
async def legal_versions(request: Request):
    """Current Terms of Service / Privacy Policy versions the sign-up form must submit."""
    return APIResponse.ok(ConsentService.versions())
