"""Fail-closed admin handoff for manually issued AADE documents."""

from fastapi import APIRouter

from backend.app.api.endpoints.billing_admin_accounting import (
    record_issued_aade_document as record_issued_aade_document,
)
from backend.app.api.endpoints.billing_admin_accounting import (
    record_manual_refund_accounting as record_manual_refund_accounting,
)
from backend.app.api.endpoints.billing_admin_accounting import (
    router as accounting_router,
)
from backend.app.api.endpoints.billing_admin_models import (
    PendingBillingCustomer as PendingBillingCustomer,
)
from backend.app.api.endpoints.billing_admin_models import (
    PendingBillingInvoice as PendingBillingInvoice,
)
from backend.app.api.endpoints.billing_admin_models import (
    PendingBillingInvoicesResponse as PendingBillingInvoicesResponse,
)
from backend.app.api.endpoints.billing_admin_models import (
    PendingBillingPackage as PendingBillingPackage,
)
from backend.app.api.endpoints.billing_admin_models import (
    PendingBillingPayment as PendingBillingPayment,
)
from backend.app.api.endpoints.billing_admin_models import (
    PendingBillingService as PendingBillingService,
)
from backend.app.api.endpoints.billing_admin_models import (
    PendingBillingTax as PendingBillingTax,
)
from backend.app.api.endpoints.billing_admin_models import (
    PendingRefundReview as PendingRefundReview,
)
from backend.app.api.endpoints.billing_admin_models import (
    PendingRefundReviewsResponse as PendingRefundReviewsResponse,
)
from backend.app.api.endpoints.billing_admin_models import (
    PendingWithdrawalAdjustment as PendingWithdrawalAdjustment,
)
from backend.app.api.endpoints.billing_admin_models import (
    PendingWithdrawalReview as PendingWithdrawalReview,
)
from backend.app.api.endpoints.billing_admin_models import (
    PendingWithdrawalReviewsResponse as PendingWithdrawalReviewsResponse,
)
from backend.app.api.endpoints.billing_admin_models import (
    RecordedAadeDocumentResponse as RecordedAadeDocumentResponse,
)
from backend.app.api.endpoints.billing_admin_models import (
    RecordedManualRefundAccountingResponse as RecordedManualRefundAccountingResponse,
)
from backend.app.api.endpoints.billing_admin_models import (
    RecordIssuedAadeDocumentRequest as RecordIssuedAadeDocumentRequest,
)
from backend.app.api.endpoints.billing_admin_models import (
    RecordManualRefundAccountingRequest as RecordManualRefundAccountingRequest,
)
from backend.app.api.endpoints.billing_admin_models import (
    ResolveWithdrawalRequest as ResolveWithdrawalRequest,
)
from backend.app.api.endpoints.billing_admin_models import (
    WithdrawalResolutionResponse as WithdrawalResolutionResponse,
)
from backend.app.api.endpoints.billing_admin_reviews import (
    list_pending_billing_invoices as list_pending_billing_invoices,
)
from backend.app.api.endpoints.billing_admin_reviews import (
    list_pending_refund_reviews as list_pending_refund_reviews,
)
from backend.app.api.endpoints.billing_admin_reviews import (
    list_pending_withdrawal_reviews as list_pending_withdrawal_reviews,
)
from backend.app.api.endpoints.billing_admin_reviews import router as reviews_router
from backend.app.api.endpoints.billing_admin_withdrawals import (
    resolve_withdrawal_review as resolve_withdrawal_review,
)
from backend.app.api.endpoints.billing_admin_withdrawals import (
    router as withdrawal_router,
)

router = APIRouter()
router.include_router(reviews_router)
router.include_router(accounting_router)
router.include_router(withdrawal_router)
