"""
Global boto3 session manager — request-scoped via contextvars.
Credentials injected at request time from Electron keychain.
Includes adaptive retry configuration.
"""
from __future__ import annotations
from contextvars import ContextVar
import boto3
from botocore.config import Config

_session_var: ContextVar[boto3.Session] = ContextVar("aws_session")

# Adaptive retry: auto back-off on throttling / transient errors
BOTO_CONFIG = Config(
    retries={"max_attempts": 3, "mode": "adaptive"},
    connect_timeout=5,
    read_timeout=15,
)


def set_session(credentials: dict, profile: str = "default") -> boto3.Session:
    """Build and store a boto3 session for the current async context."""
    if credentials.get("aws_access_key_id"):
        session = boto3.Session(
            aws_access_key_id=credentials["aws_access_key_id"],
            aws_secret_access_key=credentials["aws_secret_access_key"],
            aws_session_token=credentials.get("aws_session_token"),
            region_name=credentials.get("aws_region", "us-east-1"),
        )
    else:
        session = boto3.Session(
            profile_name=profile if profile != "default" else None
        )
    _session_var.set(session)
    return session


def get_session() -> boto3.Session:
    """Get the current request's boto3 session. Falls back to default."""
    try:
        return _session_var.get()
    except LookupError:
        session = boto3.Session()
        _session_var.set(session)
        return session


def get_client(service: str, region: str = "us-east-1"):
    """Get a boto3 client with retry config attached."""
    return get_session().client(service, region_name=region, config=BOTO_CONFIG)
