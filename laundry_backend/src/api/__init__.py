"""
FastAPI application package.

This package exposes the FastAPI `app` object at the package level so common
deployment commands like `uvicorn src.api:app` work as expected.
"""

from .main import app  # noqa: F401
