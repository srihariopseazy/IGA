from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AccessRequestItemCreate(BaseModel):
    """A single item (role, entitlement, application) being requested."""
    item_type: str = Field(
        pattern="^(role|entitlement|application|permission)$",
        description="Type of access being requested",
    )
    item_id: uuid.UUID = Field(description="ID of the role/entitlement/application")
    justification: Optional[str] = Field(default=None, max_length=1000)


class AccessRequestCreate(BaseModel):
    target_user_id: uuid.UUID = Field(description="User who needs the access (self or managed user)")
    items: List[AccessRequestItemCreate] = Field(min_length=1, max_length=50)
    justification: str = Field(min_length=10, max_length=2000)
    priority: str = Field(
        default="normal",
        pattern="^(low|normal|high|critical)$",
    )
    temporary: bool = False
    valid_until: Optional[datetime] = Field(
        default=None,
        description="Expiry date for temporary access",
    )
    business_justification: Optional[str] = Field(default=None, max_length=2000)
    ticket_reference: Optional[str] = Field(
        default=None, max_length=100, description="External ticket/JIRA reference"
    )
    notify_on_complete: bool = True


class AccessRequestItemResponse(BaseModel):
    id: uuid.UUID
    item_type: str
    item_id: uuid.UUID
    item_name: Optional[str] = None
    item_description: Optional[str] = None
    justification: Optional[str] = None
    status: str  # pending, approved, rejected, provisioned, failed
    provisioned_at: Optional[datetime] = None
    provisioning_error: Optional[str] = None

    model_config = {"from_attributes": True}


class ApprovalStepResponse(BaseModel):
    id: uuid.UUID
    step_order: int
    approver_id: Optional[uuid.UUID] = None
    approver_name: Optional[str] = None
    approver_email: Optional[str] = None
    delegated_to_id: Optional[uuid.UUID] = None
    status: str  # pending, approved, rejected, delegated, skipped
    comments: Optional[str] = None
    decided_at: Optional[datetime] = None
    due_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class StatusTimelineEntry(BaseModel):
    status: str
    changed_at: datetime
    changed_by: Optional[str] = None
    comment: Optional[str] = None


class AccessRequestResponse(BaseModel):
    id: uuid.UUID
    request_number: Optional[str] = None
    requester_id: uuid.UUID
    requester_name: Optional[str] = None
    requester_email: Optional[str] = None
    target_user_id: uuid.UUID
    target_user_name: Optional[str] = None
    target_user_email: Optional[str] = None
    tenant_id: uuid.UUID
    status: str  # draft, pending, approved, rejected, cancelled, provisioning, completed, failed
    priority: str
    temporary: bool
    valid_until: Optional[datetime] = None
    justification: str
    business_justification: Optional[str] = None
    ticket_reference: Optional[str] = None
    items: List[AccessRequestItemResponse] = Field(default_factory=list)
    approval_steps: List[ApprovalStepResponse] = Field(default_factory=list)
    status_timeline: List[StatusTimelineEntry] = Field(default_factory=list)
    submitted_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    metadata: Optional[Dict[str, Any]] = None

    model_config = {"from_attributes": True}


class ApprovalAction(BaseModel):
    """Approve or reject an access request."""
    action: str = Field(pattern="^(approve|reject)$")
    comments: Optional[str] = Field(default=None, max_length=2000)
    conditions: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Conditions/restrictions on approval",
    )


class DelegateApprovalRequest(BaseModel):
    delegate_to_user_id: uuid.UUID
    reason: Optional[str] = Field(default=None, max_length=500)
    expires_at: Optional[datetime] = None


class BulkApprovalRequest(BaseModel):
    request_ids: List[uuid.UUID] = Field(min_length=1, max_length=100)
    action: str = Field(pattern="^(approve|reject)$")
    comments: Optional[str] = Field(default=None, max_length=2000)


class CancelRequestBody(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


class AccessRequestListResponse(BaseModel):
    items: List[AccessRequestResponse]
    total: int
    page: int
    per_page: int
    pages: int


class AccessRequestSearchParams(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    requester_id: Optional[uuid.UUID] = None
    target_user_id: Optional[uuid.UUID] = None
    submitted_after: Optional[datetime] = None
    submitted_before: Optional[datetime] = None
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=100)
    sort_by: str = "created_at"
    sort_order: str = Field(default="desc", pattern="^(asc|desc)$")
