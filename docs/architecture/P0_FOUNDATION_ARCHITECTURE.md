# P0 Foundation Architecture

## Overview
The AI Legal Helper is designed as a standalone Python project integrating various components of AI-driven legal services. 
In the P0 phase, we establish the foundation with a clear directory structure, modular packages, and standard configurations (`pyproject.toml`, Streamlit for UI).

## Directory Structure
- `src/ai_legal_helper/`: Main package.
  - `core/`: Core configuration and exceptions.
  - `observability/`: AOP logging, OpenTelemetry integration, context variables.
  - `llm/`: LLM Gateway, usage tracking, LangChain callbacks.
  - `ui/`: Streamlit based UI entrypoints.
- `tests/`: Pytest test suites.
- `docs/`: Architecture and development records.

## Build and Dependency Management
- We use `pyproject.toml` with `hatchling` as the build backend.
- Managed virtual environment using standard `venv`.

## Future Extensions (P1+)
- `agents/` and `workflows/` will house LangGraph based agent orchestrations.
- `rag/` and `cases/` will integrate Chroma DB and document retrieval.
- `integrations/legacy_legal/` will safely interact with the previous system without mutating its code.

