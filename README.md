# AEGIS — Dynamic Policy Rules Engine for AI Agents

**Aivar Innovations Agentic AI Challenge — PS-10.2**

AEGIS is a production-oriented governance runtime that dynamically evaluates AI agent actions against runtime context and determines appropriate governance decisions.

## Architecture

```
LLM Proposes → AEGIS Governs → Tools Execute Only After Governance
```

Core flow:
- AI Agent proposes a structured tool action
- AEGIS constructs runtime context from server-side session state
- Policy resolver loads and merges policies (with inheritance)
- Rule evaluator deterministically evaluates conditions
- Decision engine selects the highest-severity matched decision
- Enforcement gateway executes the decision (ALLOW/BLOCK/HITL/SUSPEND)

## Current Status: Milestone 1 — Core Governance Engine

### Implemented
- [x] Deterministic policy DSL (YAML-based, no eval/exec)
- [x] Policy validation (fields, operators, types, decisions)
- [x] Policy inheritance (single-parent, circular detection)
- [x] Rule evaluator (pure function, no side effects)
- [x] Decision engine (severity + priority ordering)
- [x] Runtime context builder (server-derived violation counts)
- [x] Violation threshold logic (3rd violation → SUSPEND_SESSION)
- [x] Database models (SQLAlchemy async, PostgreSQL-compatible)
- [x] Core unit tests (15 test scenarios)

### Not Yet Implemented
- [ ] REST API endpoints (Milestone 2)
- [ ] Real LLM integration (Milestone 2)
- [ ] HITL workflow endpoints (Milestone 2)
- [ ] Frontend dashboard (Milestone 2)
- [ ] Cloud deployment (Milestone 3)

## Quick Start

### Prerequisites
- Python 3.11+
- pip

### Setup
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate    # Windows
source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
```

### Environment
```bash
cp ../.env.example ../.env
```

### Run Tests
```bash
cd backend
python -m pytest tests/ -v
```

### Start Server
```bash
cd backend
uvicorn app.main:app --reload
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| DATABASE_URL | sqlite+aiosqlite:///./aegis.db | Database connection string |
| BUSINESS_HOURS_START | 09:00 | Business hours start (UTC) |
| BUSINESS_HOURS_END | 17:00 | Business hours end (UTC) |
| VIOLATION_THRESHOLD | 3 | Violations before session suspension |
| LLM_PROVIDER | mock | LLM provider (mock/gemini) |
| DEFAULT_POLICY_ID | base_policy | Default policy for new sessions |

## Policy DSL

Policies are defined in YAML with deterministic, declarative conditions:

```yaml
rules:
  - id: example_rule
    priority: 100
    decision: BLOCK
    condition:
      all:
        - field: action.type
          operator: equals
          value: write
        - field: context.is_business_hours
          operator: equals
          value: false
```

### Supported Operators
equals, not_equals, greater_than, greater_than_or_equals, less_than, less_than_or_equals, in, not_in, contains

### Governance Decisions
ALLOW, BLOCK, REQUIRE_HITL, SUSPEND_SESSION

## License
Internal — Aivar Innovations Challenge
