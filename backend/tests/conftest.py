import pytest
from pathlib import Path
from datetime import datetime
from app.core.models import ProposedAction, RuntimeContext
from app.core.policy_loader import PolicyLoader
from app.core.policy_resolver import PolicyResolver
from app.core.rule_evaluator import RuleEvaluator
from app.core.decision_engine import DecisionEngine
from app.core.context_builder import ContextBuilder
from app.services.governance_service import GovernanceService


@pytest.fixture(autouse=True)
def clear_settings_cache():
    from app.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def sample_write_action():
    return ProposedAction(tool="update_patient", arguments={"patient_id": "P101"}, action_type="write", data_scope_size=1)


@pytest.fixture
def sample_read_action():
    return ProposedAction(tool="search_patient", arguments={}, action_type="read", data_scope_size=1)


@pytest.fixture
def sample_delete_action():
    return ProposedAction(tool="delete_patient", arguments={"patient_id": "P101"}, action_type="delete", data_scope_size=1)


@pytest.fixture
def business_hours_context():
    def _context(previous_violations=0):
        # Tuesday Aug 18 2026, 10:00 UTC
        return RuntimeContext(
            timestamp=datetime(2026, 8, 18, 10, 0, 0),
            user_role="nurse",
            session_data_classification="internal",
            agent_id="aegis-agent-01",
            action_type="write",
            data_scope_size=1,
            previous_violations_in_session=previous_violations,
            session_id="test-session-1",
            is_business_hours=True,
            session_status="active",
        )
    return _context


@pytest.fixture
def after_hours_context():
    def _context(previous_violations=0):
        # Tuesday Aug 18 2026, 23:00 UTC
        return RuntimeContext(
            timestamp=datetime(2026, 8, 18, 23, 0, 0),
            user_role="nurse",
            session_data_classification="internal",
            agent_id="aegis-agent-01",
            action_type="write",
            data_scope_size=1,
            previous_violations_in_session=previous_violations,
            session_id="test-session-1",
            is_business_hours=False,
            session_status="active",
        )
    return _context


@pytest.fixture
def phi_external_context():
    def _context(previous_violations=0):
        return RuntimeContext(
            timestamp=datetime(2026, 8, 18, 10, 0, 0),
            user_role="external",
            session_data_classification="PHI",
            agent_id="aegis-agent-01",
            action_type="read",
            data_scope_size=1,
            previous_violations_in_session=previous_violations,
            session_id="test-session-2",
            is_business_hours=True,
            session_status="active",
        )
    return _context


@pytest.fixture
def loaded_policies():
    policy_dir = Path(__file__).parent.parent.parent / "policies"
    loader = PolicyLoader()
    return loader.load_policies_from_directory(policy_dir)


@pytest.fixture
def policy_resolver():
    return PolicyResolver()


@pytest.fixture
def rule_evaluator():
    return RuleEvaluator()


@pytest.fixture
def decision_engine():
    return DecisionEngine()


@pytest.fixture
def context_builder():
    return ContextBuilder()


@pytest.fixture
def governance_service():
    service = GovernanceService()
    policy_dir = Path(__file__).parent.parent.parent / "policies"
    service.load_policies_from_directory(policy_dir)
    return service


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def async_client():
    import os
    import httpx
    from app.main import app as fastapi_app
    from app.config import get_settings
    
    settings = get_settings()
    original_db_url = settings.DATABASE_URL
    original_seed = settings.SEED_DEMO_DATA
    
    # Use isolated test DB for integration tests
    settings.DATABASE_URL = "sqlite+aiosqlite:///./test_aegis.db"
    settings.SEED_DEMO_DATA = True
    
    # Cleanup previous test db if any
    if os.path.exists("./test_aegis.db"):
        try:
            os.remove("./test_aegis.db")
        except Exception:
            pass
            
    # Explicitly import models to register them with SQLAlchemy Base.metadata
    from app.db import models as _models
    from app.db import database as db_module
    from app.main import sync_policies, seed_demo_data
    
    db_module._check_db_init()
    async with db_module.engine.begin() as conn:
        await conn.run_sync(db_module.Base.metadata.drop_all)
        await conn.run_sync(db_module.Base.metadata.create_all)
        
    await sync_policies()
    await seed_demo_data()
            
    from httpx import ASGITransport
    async with httpx.AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as ac:
        yield ac
        
    # Reset settings and cleanup
    settings.DATABASE_URL = original_db_url
    settings.SEED_DEMO_DATA = original_seed
    
    # We delay removing the database file briefly to ensure all async pool connections are closed
    # but a simple try-except is fine.
    if os.path.exists("./test_aegis.db"):
        try:
            os.remove("./test_aegis.db")
        except Exception:
            pass

