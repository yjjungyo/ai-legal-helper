# P1 Integration & Architecture Review

## 1. Adapter Monkey-Patching (adapter.py)
**Cause**: `adapter.py` globally mutates `legacy_config.get_llm` and `legacy_config.get_temp_llm` to inject the P0 `TokenTracker`.
**Impact**: Modifying global state affects the entire Python process. Since FastAPI handles concurrent requests in the same process, global patching can cause side-effects or race conditions if other components rely on the original LLM instances.
**Improvement Plan**: Instead of monkey-patching, utilize explicit Dependency Injection if the legacy graph builder supports it. Alternatively, use `unittest.mock.patch` as a context manager strictly scoped around the graph execution, or subclass/wrap the legacy workflow without polluting global module namespaces.

## 2. Legacy Module Loading
**Cause**: `sys.path.insert(0, LEGACY_PATH)` is used to resolve `src` from `ai-legal-agent`.
**Impact**: The package namespace `src` is highly generic. Any internal imports like `from src.config import...` inside `ai-legal-helper` or its future dependencies might accidentally resolve to the legacy `src` folder, risking `ModuleNotFoundError` or unpredictable behavior.
**Improvement Plan**: Refactor the legacy project into a standard installable Python package (e.g., `pip install -e ../ai-legal-agent`) with a distinct top-level namespace like `ai_legal_agent` instead of `src`. Alternatively, isolate the legacy execution in a separate microservice.

## 3. Relative Path Dependencies (storage folder)
**Cause**: The legacy configuration (`config.py`) hardcodes relative paths like `./storage/app.log`.
**Impact**: When executing FastAPI from the new `ai-legal-helper` root, these paths resolve relative to the new CWD (`C:\myprjs\ai-legal-helper`). This forced the creation of a `storage` directory in the new root to avoid `FileNotFoundError`. The legacy logs are now split from their original location, breaking existing logging contexts.
**Improvement Plan**: Inject absolute paths via environment variables (e.g., `os.environ["LOG_PATH"] = ...`) in the adapter *before* the legacy configuration is imported.

## 4. FastAPI BackgroundTasks & Memory State
**Cause**: `main.py` uses FastAPI's built-in `BackgroundTasks` along with an in-memory dictionary `_consultations` to track asynchronous workflow state.
**Impact**: 
- **State Loss**: All job statuses and results are lost upon server restart or crash.
- **Memory Leak**: The dictionary grows indefinitely because there is no TTL or eviction policy implemented.
- **Unscalable**: This pattern cannot scale horizontally. In a multi-worker environment (e.g., Uvicorn with multiple workers or Kubernetes deployments), requests routed to worker A will not be retrievable by polling worker B.
**Improvement Plan**: Migrate workflow state to a persistent external store like Redis or PostgreSQL. Replace `BackgroundTasks` with a dedicated async task queue (e.g., Celery, RQ, TaskIQ) for executing long-running Agent workflows.

## 5. Token Tracking Coverage in Legacy Code
**Cause**: The legacy agents import `get_temp_llm` directly from `src.config`. Since the adapter patches these factory functions correctly, the P0 callbacks *are* successfully attached.
**Impact**: The P0 `TokenTrackingCallbackHandler` successfully captures the LLM usage. Because the adapter uses `contextvars.copy_context()` and runs the graph in a thread, the `trace_id` propagates correctly. However, the legacy agents do not actively set `agent_name` or `node_name` into the `ai_legal_helper` context. Consequently, tokens are accurately tracked per trace, but structural granularity is lost (fields are logged as `"unknown"`).
**Improvement Plan**: Inject custom LangChain Callbacks designed to parse the LangChain run context (e.g., reading `run_name` or tags) to dynamically infer and populate `agent_name` and `node_name` for legacy operations.

## 6. Chroma RAG Search Success
**Cause**: The legacy vector database path is set to `CHROMA_PERSIST = "./vectorstore/chroma"`.
**Impact**: Due to the CWD shift to `ai-legal-helper`, the RAG nodes are searching `C:\myprjs\ai-legal-helper\vectorstore\chroma`, which does not exist (the actual data resides in `C:\myprjs\ai-legal-agent\vectorstore\chroma`). As a result, Chroma RAG queries are silently failing or returning empty contexts, likely causing the legacy agent to hallucinate or rely entirely on pre-trained knowledge without citations.
**Improvement Plan**: In `adapter.py`, explicitly set `os.environ["CHROMA_PERSIST"] = os.path.join(LEGACY_PATH, "vectorstore", "chroma")` before loading the legacy module to route the vector search to the correct data folder.

