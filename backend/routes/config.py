from fastapi import APIRouter, Depends
from backend.middleware.auth import get_current_user
from backend.models.user import User

router = APIRouter(prefix="/config", tags=["Config"])


@router.get("")
async def get_config(current_user: User = Depends(get_current_user)):
    """Return tenant feature config."""
    return {
        "features": {
            "mfa_enabled": True,
            "sod_enabled": True,
            "certifications_enabled": True,
            "pam_enabled": True,
            "risk_scoring_enabled": True,
            "ai_recommendations_enabled": True,
        },
        "tenant_id": str(current_user.tenant_id),
    }
