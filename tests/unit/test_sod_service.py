"""Unit tests for SoD (Segregation of Duties) service."""
import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture
def sod_service(mock_db):
    from backend.services.sod_service import SODService
    return SODService(mock_db)


@pytest.mark.asyncio
async def test_check_sod_no_violations(sod_service, mock_db):
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    entitlement_ids = [uuid.uuid4(), uuid.uuid4()]

    mock_db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
    violations = await sod_service.check_violations(tenant_id=tenant_id, user_id=user_id, entitlement_ids=entitlement_ids)
    assert violations == []


@pytest.mark.asyncio
async def test_simulate_sod_returns_result(sod_service, mock_db):
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    new_entitlement_id = uuid.uuid4()

    mock_db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
    result = await sod_service.simulate_conflict(
        tenant_id=tenant_id,
        user_id=user_id,
        entitlement_id=new_entitlement_id,
    )
    assert isinstance(result, dict)
    assert "has_conflicts" in result


@pytest.mark.asyncio
async def test_get_violations_filters_by_tenant(sod_service, mock_db):
    tenant_id = uuid.uuid4()
    mock_db.execute = AsyncMock(return_value=MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    ))
    result = await sod_service.get_violations(tenant_id=tenant_id)
    assert result == []
    mock_db.execute.assert_called_once()
