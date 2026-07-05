import logging

from fastapi import APIRouter, HTTPException, Request

from app.middleware import limiter
from app.schemas.common import APIResponse
from app.schemas.contact import ContactRequest, ContactResponse
from app.services.email_service import send_contact_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contact", tags=["contact"])


@router.post("", response_model=APIResponse[ContactResponse])
@limiter.limit("5/minute")
async def submit_contact(request: Request, body: ContactRequest):
    if not body.consent:
        raise HTTPException(status_code=400, detail="Consent is required")

    try:
        send_contact_email(
            first_name=body.first_name,
            last_name=body.last_name,
            email=body.email,
            company=body.company,
            job_title=body.job_title,
            phone=body.phone,
            country=body.country,
            inquiry_type=body.inquiry_type,
            message=body.message,
        )
    except Exception:
        logger.exception("Failed to send contact email")
        raise HTTPException(status_code=502, detail="Failed to deliver message")

    return APIResponse.ok(ContactResponse(message="Message sent"))
