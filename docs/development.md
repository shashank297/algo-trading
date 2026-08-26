# Developer Guide & Quality Verification

This guide outlines development workflows, coding standards, quality assurance gates, and commit discipline for the AlgoTrading repository.

---

## 1. Environment Setup

### Prerequisites
- Python `3.12` or `3.13` on Windows, Linux, or macOS
- Node.js `20+` (for Dashboard UI development)
- Git

### Virtual Environment Initialization
```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
```

---

## 2. Coding Standards & Architectural Guidelines

- **Python Standards**: Use Python 3.12+ syntax, four-space indentation, explicit type hints on all public functions/methods, and short explanatory docstrings.
- **Naming Conventions**:
  - `snake_case` for modules, functions, variables, and database columns.
  - `PascalCase` for classes, dataclasses, and exceptions.
  - `UPPERCASE` for constants and Enum members.
- **Causal Architecture**: Strategy logic must be strictly causal and provider-neutral. Never use future bars, unshifted volume, or today's unclosed candle.
- **Single-Writer Constraint**: DuckDB operates under a strict single-writer lock. Never spawn concurrent processes that write to `market_data.duckdb`.
- **Surgical Changes**: Keep edits focused and surgical. Avoid broad refactorings or modifying established schema migrations.

---

## 3. Comprehensive Verification Gates

Before submitting changes or pushing commits, every gate in the quality suite must pass cleanly:

```powershell
# 1. Deterministic Unit & Integration Tests (387 tests)
.\venv\Scripts\python.exe -m pytest -q

# 2. Linting & Code Style
.\venv\Scripts\python.exe -m ruff check .

# 3. Static Type Checking (Mypy)
.\venv\Scripts\python.exe -m mypy ai_research data_platform experiments operations orchestration risk smartapi storage trading_stack validators tools main.py research.py scheduler.py

# 4. Static Type Checking (Pyright)
npx --yes pyright

# 5. Byte Compilation
.\venv\Scripts\python.exe -m compileall -q main.py research.py scheduler.py ai_research data_platform experiments operations orchestration risk smartapi storage trading_stack validators tools tests

# 6. Global Test Coverage (>= 80%)
.\venv\Scripts\python.exe -m coverage erase
.\venv\Scripts\python.exe -m coverage run -m pytest -q
.\venv\Scripts\python.exe -m coverage report --fail-under=80

# 7. Critical Path Module Coverage (>= 95%)
.\venv\Scripts\python.exe -m coverage report --include="risk/*.py,trading_stack/paper.py,trading_stack/portfolio.py,trading_stack/portfolio_paper.py,trading_stack/pipeline.py,trading_stack/datasets.py,trading_stack/certification.py,trading_stack/promotion.py,smartapi/websocket_client.py,trading_stack/live_aggregator.py,storage/migrations/*.py" --fail-under=95

# 8. Dependency Security Audit
.\venv\Scripts\python.exe -m pip_audit -r requirements.txt

# 9. Dashboard UI Lint & Build
cd tools\dashboard\ui
npm run lint
npm run build
cd ..\..\..
```

---

## 4. Two-Commit Discipline

All architectural remediations and feature additions must follow the strict **Two-Commit Discipline**:

1. **Commit A (Code & Tests)**:
   - Stage only source code and test files (`tests/`, `trading_stack/`, `smartapi/`, etc.). Exclude `docs/`.
   - Run the full verification suite.
   - Commit: `git commit -m "Commit A: <concise imperative description of code fixes>"`
   - Record the exact Commit A SHA via `git rev-parse HEAD`.

2. **Documentation & Verification**:
   - Update `docs/production_readiness.md` and `docs/traceability_matrix.md` with the exact Commit A SHA, test pass count, and verified coverage numbers.

3. **Commit B (Documentation Only)**:
   - Stage only `docs/` files.
   - Commit: `git commit -m "Commit B: Update final production readiness evidence"`

4. **Push to Remote**:
   - `git push origin main`
