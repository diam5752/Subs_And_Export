"""Application environment helpers shared across the backend."""

from __future__ import annotations

import os
from enum import StrEnum


class AppEnv(StrEnum):
    DEV = "dev"
    PRODUCTION = "production"


_DEV_ALIASES = {"dev", "development", "local", "localhost"}
_PROD_ALIASES = {"prod", "production"}


def normalize_app_env(value: str | None) -> AppEnv:
    """
    Normalize an environment string into a known application environment.

    Defaults to DEV when unset, and treats unknown values as PRODUCTION to avoid
    accidentally enabling dev-only behavior.
    """
    if value is None:
        return AppEnv.DEV
    lowered = value.strip().lower()
    if lowered in _DEV_ALIASES:
        return AppEnv.DEV
    if lowered in _PROD_ALIASES:
        return AppEnv.PRODUCTION
    return AppEnv.PRODUCTION


def get_app_env() -> AppEnv:
    return normalize_app_env(os.getenv("APP_ENV") or os.getenv("ENV"))


def is_dev_env() -> bool:
    return get_app_env() == AppEnv.DEV

