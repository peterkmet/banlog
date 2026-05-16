# CLAUDE.md — Instructions for Claude

## Workflow Rules

- **Never generate code without approval.** Always describe what you plan to change and wait for explicit confirmation before writing any code.
- No unsolicited code — every change requires an explicit prompt.
- Keep it simple. No over-engineering. MVP first.

## Coding Conventions

- All code, comments, and documentation in **English**.

## Running Tests

```bash
uv run pytest tests/unit/
uv run pytest -m integration
```

## Linting

```bash
uv run ruff check src/
uv run ruff format --check src/
uv run mypy src/
```

## Session Start

At the beginning of every session, read `docs/prd.md` to refresh context on current requirements and project state.

## Compact Instructions

When compacting context, preserve in this order:
1. Architectural decisions (NEVER summarize)
2. Modified files and key changes
3. Verification state (pass/fail)
4. Open TODOs and rollback notes
5. Tool outputs (can be deleted, keep only pass/fail)
