# ADR 001: Project Structure

**Date**: 2026-10-08
**Status**: Accepted

## Context
We need a robust, scalable structure for a new legal AI helper that integrates but does not mutate the existing legacy legal system. 

## Decision
We adopted a standard Python `src-layout` with `pyproject.toml` instead of legacy `setup.py` or flat structures.
We explicitly forbid Docker in P0 and avoid proprietary frameworks like LangSmith, relying on open-source libraries.

## Consequences
- Clean separation of internal packages.
- Easy to package and install using standard tools (`pip install -e .`).
- Protects against accidental namespace collisions.

