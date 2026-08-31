"""Shared structural contract and facade-backed billing seams."""

from __future__ import annotations

from typing import Any

from backend.app.core.database import Database
from backend.app.services.billing_types import BillingGateway, CreditPackage
from backend.app.services.points import PointsStore


class BillingServiceMixinBase:
    db: Database
    points_store: PointsStore
    _gateway: BillingGateway | None

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)

    @staticmethod
    def _catalog_version() -> str:
        from backend.app.services import billing

        return billing.CATALOG_VERSION

    @staticmethod
    def _manual_capture_policy() -> str:
        from backend.app.services import billing

        return billing.MANUAL_CAPTURE_POLICY

    @staticmethod
    def _consumer_contract_registry_is_approved() -> bool:
        from backend.app.services import billing

        return billing.consumer_contract_registry_is_approved()

    @staticmethod
    def _stripe_gateway_factory() -> BillingGateway:
        from backend.app.services import billing

        return billing.StripeSdkGateway()

    @staticmethod
    def _credit_packages() -> tuple[CreditPackage, ...]:
        from backend.app.services import billing

        return billing.credit_packages()
