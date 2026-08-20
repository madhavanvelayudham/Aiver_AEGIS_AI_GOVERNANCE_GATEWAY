import yaml
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.config import get_settings
from app.db.database import init_db, SessionLocal
from app.db.models import PolicyModel, PolicyVersionModel, AgentModel, SessionModel
from app.core.policy_loader import PolicyLoader
from app.services.governance_service import (
    SessionNotFoundError, PolicyNotFoundError, SuspendedSessionError, InvalidGovernanceStateError
)
from app.api.v1.health import router as health_router
from app.api.v1.governance import router as governance_router
from app.api.v1.agent import router as agent_router
from app.api.v1.hitl import router as hitl_router

async def sync_policies():
    """Reads YAML policies from directory and synchronizes them to DB tables on startup."""
    policy_dir = Path("D:/AIver_One_day/policies")
    loader = PolicyLoader()
    # Verify policy validity at startup
    loader.load_policies_from_directory(policy_dir)
    
    async with SessionLocal() as db:
        for file_path in policy_dir.glob("*.yaml"):
            content = file_path.read_text()
            parsed = yaml.safe_load(content)
            policy_id = parsed["id"]
            version = parsed.get("version", 1)
            extends = parsed.get("extends")
            name = parsed.get("name", policy_id)
            description = parsed.get("description", "")
            
            # Sync PolicyModel
            stmt = select(PolicyModel).where(PolicyModel.id == policy_id)
            res = await db.execute(stmt)
            policy_orm = res.scalar_one_or_none()
            
            if not policy_orm:
                policy_orm = PolicyModel(
                    id=policy_id,
                    name=name,
                    description=description,
                    extends_id=extends,
                    active_version=version
                )
                db.add(policy_orm)
            else:
                policy_orm.name = name
                policy_orm.description = description
                policy_orm.extends_id = extends
                policy_orm.active_version = version
            
            await db.flush()
            
            # Sync PolicyVersionModel
            stmt_ver = select(PolicyVersionModel).where(
                PolicyVersionModel.policy_id == policy_id,
                PolicyVersionModel.version == version
            )
            res_ver = await db.execute(stmt_ver)
            ver_orm = res_ver.scalar_one_or_none()
            
            if not ver_orm:
                ver_orm = PolicyVersionModel(
                    policy_id=policy_id,
                    version=version,
                    yaml_content=content,
                    parsed_rules=parsed.get("rules", []),
                    status="active"
                )
                db.add(ver_orm)
            else:
                ver_orm.yaml_content = content
                ver_orm.parsed_rules = parsed.get("rules", [])
            
            await db.flush()
        await db.commit()

async def seed_demo_data():
    """Seeds default testing agent and sessions (CORRECTION 3: only run if SEED_DEMO_DATA is True)."""
    async with SessionLocal() as db:
        # Sync Default Agent
        stmt = select(AgentModel).where(AgentModel.id == "aegis-agent-01")
        res = await db.execute(stmt)
        agent = res.scalar_one_or_none()
        
        if not agent:
            agent = AgentModel(
                id="aegis-agent-01",
                name="Default Agent",
                description="Default AEGIS Agent for testing",
                is_active=True
            )
            db.add(agent)
            await db.flush()
            
        # Sync Default test sessions
        sessions_to_seed = [
            {
                "id": "test-session-allow",
                "user_role": "nurse",
                "data_classification": "internal",
                "active_policy_id": "base_policy",
                "previous_violations": 0,
                "status": "active"
            },
            {
                "id": "test-session-after-hours",
                "user_role": "nurse",
                "data_classification": "internal",
                "active_policy_id": "base_policy",
                "previous_violations": 0,
                "status": "active"
            },
            {
                "id": "test-session-phi",
                "user_role": "external",
                "data_classification": "PHI",
                "active_policy_id": "healthcare_policy",
                "previous_violations": 0,
                "status": "active"
            },
            {
                "id": "test-session-violation",
                "user_role": "nurse",
                "data_classification": "internal",
                "active_policy_id": "base_policy",
                "previous_violations": 2,
                "status": "active"
            },
            {
                "id": "test-session-suspended",
                "user_role": "nurse",
                "data_classification": "internal",
                "active_policy_id": "base_policy",
                "previous_violations": 3,
                "status": "suspended"
            }
        ]
        
        for s_data in sessions_to_seed:
            stmt_sess = select(SessionModel).where(SessionModel.id == s_data["id"])
            res_sess = await db.execute(stmt_sess)
            sess = res_sess.scalar_one_or_none()
            if not sess:
                sess = SessionModel(
                    id=s_data["id"],
                    agent_id="aegis-agent-01",
                    user_role=s_data["user_role"],
                    data_classification=s_data["data_classification"],
                    active_policy_id=s_data["active_policy_id"],
                    previous_violations=s_data["previous_violations"],
                    status=s_data["status"]
                )
                db.add(sess)
        await db.commit()

def register_exception_handlers(app: FastAPI):
    """Maps transport-independent domain exceptions to FastAPI HTTP responses (CORRECTION 1)."""
    @app.exception_handler(SessionNotFoundError)
    async def session_not_found_handler(request: Request, exc: SessionNotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})
        
    @app.exception_handler(PolicyNotFoundError)
    async def policy_not_found_handler(request: Request, exc: PolicyNotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})
        
    @app.exception_handler(SuspendedSessionError)
    async def suspended_session_handler(request: Request, exc: SuspendedSessionError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})
        
    @app.exception_handler(InvalidGovernanceStateError)
    async def invalid_state_handler(request: Request, exc: InvalidGovernanceStateError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AEGIS",
        description="Dynamic Policy Rules Engine for AI Agents",
        version="0.1.0",
        docs_url="/docs"
    )
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS.split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Register endpoints
    app.include_router(health_router)
    app.include_router(governance_router, prefix="/api/v1")
    app.include_router(agent_router, prefix="/api/v1")
    app.include_router(hitl_router, prefix="/api/v1")
    
    # Serve index.html at root
    @app.get("/", response_class=HTMLResponse)
    async def get_dashboard():
        index_path = Path(__file__).parent / "static" / "index.html"
        if index_path.exists():
            return index_path.read_text(encoding="utf-8")
        return "<h3>AEGIS Dashboard Page Loading...</h3>"

    # Mount static files folder
    static_path = Path(__file__).parent / "static"
    if not static_path.exists():
        static_path.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")
    
    # Register exceptions mappings
    register_exception_handlers(app)
    
    @app.on_event("startup")
    async def startup():
        await init_db()
        await sync_policies()
        if settings.SEED_DEMO_DATA:
            await seed_demo_data()
    
    return app

app = create_app()
