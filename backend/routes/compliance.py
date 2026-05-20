from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from backend.database import get_db
from backend.models.audit import AuditLog, ComplianceReport
from backend.models.certification import CertificationCampaign, CertificationItem
from backend.models.sod import SODViolation
from backend.models.user import User

router = APIRouter(prefix="/compliance", tags=["Compliance"])


class ReportGenerateRequest(BaseModel):
    report_type: str  # sox, hipaa, gdpr, iso27001, pci_dss
    period_start: datetime
    period_end: datetime


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    user_data = getattr(request.state, "user", None)
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = user_data.get("id")
    tenant_id = user_data.get("tenant_id")
    result = await db.execute(
        select(User).where(and_(User.id == user_id, User.tenant_id == tenant_id))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def _get_open_violations_count(db: AsyncSession, tenant_id) -> int:
    result = await db.execute(
        select(func.count(SODViolation.id)).where(
            and_(SODViolation.tenant_id == tenant_id, SODViolation.status == "open")
        )
    )
    return result.scalar() or 0


async def _get_cert_stats(db: AsyncSession, tenant_id) -> dict:
    total = await db.execute(
        select(func.count(CertificationItem.id)).where(CertificationItem.tenant_id == tenant_id)
    )
    certified = await db.execute(
        select(func.count(CertificationItem.id)).where(
            and_(
                CertificationItem.tenant_id == tenant_id,
                CertificationItem.status == "certified",
            )
        )
    )
    revoked = await db.execute(
        select(func.count(CertificationItem.id)).where(
            and_(
                CertificationItem.tenant_id == tenant_id,
                CertificationItem.status == "revoked",
            )
        )
    )
    total_val = total.scalar() or 0
    certified_val = certified.scalar() or 0
    revoked_val = revoked.scalar() or 0
    return {
        "total": total_val,
        "certified": certified_val,
        "revoked": revoked_val,
        "coverage": round((certified_val / total_val * 100) if total_val > 0 else 0, 1),
    }


async def _get_audit_coverage(db: AsyncSession, tenant_id) -> float:
    last_30_days = datetime.now(timezone.utc) - timedelta(days=30)
    result = await db.execute(
        select(func.count(AuditLog.id)).where(
            and_(
                AuditLog.tenant_id == tenant_id,
                AuditLog.created_at >= last_30_days,
            )
        )
    )
    count = result.scalar() or 0
    # Simple coverage score: >1000 events = 100%, scale linearly
    return min(100.0, round(count / 10, 1))


def _compute_compliance_score(violations: int, cert_coverage: float, audit_coverage: float) -> dict:
    violation_penalty = min(violations * 2, 40)
    cert_score = cert_coverage * 0.4
    audit_score = audit_coverage * 0.3
    base = 100 - violation_penalty
    score = max(0, base * 0.3 + cert_score + audit_score)
    score = round(min(100, score), 1)
    if score >= 90:
        rating = "compliant"
    elif score >= 70:
        rating = "partial"
    else:
        rating = "non_compliant"
    return {"score": score, "rating": rating}


@router.get("/status")
async def get_compliance_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = current_user.tenant_id
    violations = await _get_open_violations_count(db, tenant_id)
    cert_stats = await _get_cert_stats(db, tenant_id)
    audit_coverage = await _get_audit_coverage(db, tenant_id)

    base_scores = _compute_compliance_score(violations, cert_stats["coverage"], audit_coverage)

    standards = {
        "sox": {
            "name": "Sarbanes-Oxley",
            "controls": [
                {"id": "SOX-404", "name": "Internal Controls Assessment", "status": base_scores["rating"]},
                {"id": "SOX-302", "name": "Disclosure Controls", "status": "compliant" if violations == 0 else "partial"},
                {"id": "SOX-906", "name": "Criminal Penalties", "status": "compliant"},
            ],
            **base_scores,
        },
        "hipaa": {
            "name": "HIPAA",
            "controls": [
                {"id": "HIPAA-164.312", "name": "Technical Safeguards", "status": base_scores["rating"]},
                {"id": "HIPAA-164.308", "name": "Administrative Safeguards", "status": base_scores["rating"]},
            ],
            **base_scores,
        },
        "gdpr": {
            "name": "GDPR",
            "controls": [
                {"id": "GDPR-Art25", "name": "Data Protection by Design", "status": base_scores["rating"]},
                {"id": "GDPR-Art32", "name": "Security of Processing", "status": "compliant" if audit_coverage > 80 else "partial"},
            ],
            **base_scores,
        },
        "iso27001": {
            "name": "ISO 27001",
            "controls": [
                {"id": "A.9", "name": "Access Control", "status": "compliant" if violations == 0 else "non_compliant"},
                {"id": "A.12", "name": "Operations Security", "status": base_scores["rating"]},
            ],
            **base_scores,
        },
        "pci_dss": {
            "name": "PCI DSS",
            "controls": [
                {"id": "PCI-7", "name": "Restrict Access", "status": base_scores["rating"]},
                {"id": "PCI-10", "name": "Track and Monitor Access", "status": "compliant" if audit_coverage > 70 else "partial"},
            ],
            **base_scores,
        },
    }

    overall_score = round(sum(s["score"] for s in standards.values()) / len(standards), 1)

    return {
        "overall_score": overall_score,
        "standards": standards,
        "sod_violations_open": violations,
        "certification_coverage": cert_stats["coverage"],
        "audit_coverage": audit_coverage,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/reports")
async def list_compliance_reports(
    report_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(ComplianceReport).where(
        ComplianceReport.tenant_id == current_user.tenant_id
    )
    if report_type:
        query = query.where(ComplianceReport.report_type == report_type)
    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()
    query = query.order_by(desc(ComplianceReport.created_at)).offset((page - 1) * per_page).limit(per_page)
    rows = await db.execute(query)
    reports = rows.scalars().all()
    return {
        "items": [r.to_dict() for r in reports],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.post("/reports/generate", status_code=status.HTTP_201_CREATED)
async def generate_compliance_report(
    data: ReportGenerateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    valid_types = ["sox", "hipaa", "gdpr", "iso27001", "pci_dss"]
    if data.report_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Invalid report_type. Must be one of {valid_types}")

    report = ComplianceReport(
        tenant_id=current_user.tenant_id,
        report_type=data.report_type,
        period_start=data.period_start,
        period_end=data.period_end,
        status="generating",
        generated_by=current_user.id,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    # Queue Celery task
    try:
        from backend.tasks.compliance_tasks import generate_compliance_report_task
        generate_compliance_report_task.delay(str(report.id), str(current_user.tenant_id))
    except Exception:
        pass  # Task queuing is best-effort; report record is already created

    return report.to_dict()


@router.get("/reports/{report_id}")
async def get_compliance_report(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ComplianceReport).where(
            and_(
                ComplianceReport.id == report_id,
                ComplianceReport.tenant_id == current_user.tenant_id,
            )
        )
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report.to_dict()


@router.get("/reports/{report_id}/download")
async def download_compliance_report(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ComplianceReport).where(
            and_(
                ComplianceReport.id == report_id,
                ComplianceReport.tenant_id == current_user.tenant_id,
            )
        )
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.status != "completed" or not report.file_url:
        raise HTTPException(status_code=400, detail="Report is not ready for download")

    # Generate presigned URL via MinIO
    try:
        from minio import Minio
        from backend.config import settings
        import urllib.parse

        client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        # Extract object name from file_url
        object_name = report.file_url.split("/", 1)[-1] if "/" in report.file_url else report.file_url
        from datetime import timedelta as td
        presigned_url = client.presigned_get_object(
            settings.MINIO_BUCKET,
            object_name,
            expires=td(hours=1),
        )
        return RedirectResponse(url=presigned_url)
    except Exception as e:
        # Fallback: return the stored URL directly
        if report.file_url:
            return RedirectResponse(url=report.file_url)
        raise HTTPException(status_code=500, detail=f"Could not generate download URL: {e}")


@router.get("/sox")
async def get_sox_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = current_user.tenant_id
    violations = await _get_open_violations_count(db, tenant_id)
    cert_stats = await _get_cert_stats(db, tenant_id)
    audit_coverage = await _get_audit_coverage(db, tenant_id)
    scores = _compute_compliance_score(violations, cert_stats["coverage"], audit_coverage)
    return {
        "standard": "SOX",
        **scores,
        "controls": [
            {"id": "SOX-302", "name": "Disclosure Controls and Procedures", "status": "compliant" if violations == 0 else "non_compliant", "evidence": f"{violations} open SoD violations"},
            {"id": "SOX-404", "name": "Management Assessment of Internal Controls", "status": "compliant" if cert_stats["coverage"] > 80 else "partial", "evidence": f"{cert_stats['coverage']}% certification coverage"},
            {"id": "SOX-906", "name": "Corporate Responsibility for Financial Reports", "status": "compliant", "evidence": "Audit logging enabled"},
        ],
        "sod_violations": violations,
        "cert_coverage": cert_stats["coverage"],
    }


@router.get("/hipaa")
async def get_hipaa_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = current_user.tenant_id
    violations = await _get_open_violations_count(db, tenant_id)
    cert_stats = await _get_cert_stats(db, tenant_id)
    audit_coverage = await _get_audit_coverage(db, tenant_id)
    scores = _compute_compliance_score(violations, cert_stats["coverage"], audit_coverage)
    return {
        "standard": "HIPAA",
        **scores,
        "controls": [
            {"id": "164.308", "name": "Administrative Safeguards", "status": scores["rating"]},
            {"id": "164.310", "name": "Physical Safeguards", "status": "compliant"},
            {"id": "164.312", "name": "Technical Safeguards", "status": "compliant" if audit_coverage > 70 else "partial"},
            {"id": "164.316", "name": "Policies and Procedures", "status": "compliant" if violations == 0 else "partial"},
        ],
    }


@router.get("/gdpr")
async def get_gdpr_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = current_user.tenant_id
    violations = await _get_open_violations_count(db, tenant_id)
    cert_stats = await _get_cert_stats(db, tenant_id)
    audit_coverage = await _get_audit_coverage(db, tenant_id)
    scores = _compute_compliance_score(violations, cert_stats["coverage"], audit_coverage)
    return {
        "standard": "GDPR",
        **scores,
        "controls": [
            {"id": "Art-5", "name": "Principles of Processing", "status": scores["rating"]},
            {"id": "Art-25", "name": "Data Protection by Design", "status": "compliant"},
            {"id": "Art-32", "name": "Security of Processing", "status": "compliant" if audit_coverage > 80 else "partial"},
            {"id": "Art-35", "name": "Data Protection Impact Assessment", "status": "compliant" if violations == 0 else "partial"},
        ],
    }


@router.get("/iso27001")
async def get_iso27001_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = current_user.tenant_id
    violations = await _get_open_violations_count(db, tenant_id)
    cert_stats = await _get_cert_stats(db, tenant_id)
    audit_coverage = await _get_audit_coverage(db, tenant_id)
    scores = _compute_compliance_score(violations, cert_stats["coverage"], audit_coverage)
    return {
        "standard": "ISO 27001",
        **scores,
        "controls": [
            {"id": "A.9.1", "name": "Access Control Policy", "status": "compliant" if violations == 0 else "non_compliant"},
            {"id": "A.9.2", "name": "User Access Management", "status": "compliant" if cert_stats["coverage"] > 75 else "partial"},
            {"id": "A.12.4", "name": "Logging and Monitoring", "status": "compliant" if audit_coverage > 70 else "partial"},
            {"id": "A.18.2", "name": "Information Security Reviews", "status": scores["rating"]},
        ],
    }


@router.get("/pci-dss")
async def get_pci_dss_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = current_user.tenant_id
    violations = await _get_open_violations_count(db, tenant_id)
    cert_stats = await _get_cert_stats(db, tenant_id)
    audit_coverage = await _get_audit_coverage(db, tenant_id)
    scores = _compute_compliance_score(violations, cert_stats["coverage"], audit_coverage)
    return {
        "standard": "PCI DSS",
        **scores,
        "controls": [
            {"id": "PCI-7", "name": "Restrict Access to System Components", "status": "compliant" if violations == 0 else "non_compliant"},
            {"id": "PCI-8", "name": "Identify Users and Authenticate Access", "status": "compliant"},
            {"id": "PCI-10", "name": "Log and Monitor All Access", "status": "compliant" if audit_coverage > 80 else "partial"},
            {"id": "PCI-12", "name": "Support Information Security with Policies", "status": scores["rating"]},
        ],
    }
