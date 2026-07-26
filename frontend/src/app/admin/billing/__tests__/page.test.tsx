import React from 'react';
import {
    fireEvent,
    render,
    screen,
    waitFor,
} from '@testing-library/react';
import BillingAdminPage from '@/app/admin/billing/page';
import {
    ApiError,
    api,
    type BillingAdminPendingInvoice,
    type BillingAdminPendingRefund,
    type BillingAdminPendingWithdrawal,
    type RecordedAadeDocumentResponse,
} from '@/lib/api';

const mockUseAuth = jest.fn();

function translate(
    key: string,
    values?: Record<string, string | number>,
): string {
    if (key === 'adminBillingRecorded') {
        return `recorded:${String(values?.mark ?? '')}`;
    }
    return key;
}

jest.mock('@/lib/api', () => {
    const actual = jest.requireActual('@/lib/api');
    return {
        ...actual,
        api: {
            listPendingBillingInvoices: jest.fn(),
            recordIssuedAadeDocument: jest.fn(),
            listPendingBillingRefunds: jest.fn(),
            recordManualRefundAccounting: jest.fn(),
            listPendingBillingWithdrawals: jest.fn(),
            resolveBillingWithdrawal: jest.fn(),
        },
    };
});

jest.mock('@/context/AuthContext', () => ({
    useAuth: () => mockUseAuth(),
}));

jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({
        locale: 'en',
        t: translate,
    }),
}));

const listPendingInvoices = (
    api.listPendingBillingInvoices as jest.MockedFunction<
        typeof api.listPendingBillingInvoices
    >
);
const recordIssuedDocument = (
    api.recordIssuedAadeDocument as jest.MockedFunction<
        typeof api.recordIssuedAadeDocument
    >
);
const listPendingRefunds = (
    api.listPendingBillingRefunds as jest.MockedFunction<
        typeof api.listPendingBillingRefunds
    >
);
const listPendingWithdrawals = (
    api.listPendingBillingWithdrawals as jest.MockedFunction<
        typeof api.listPendingBillingWithdrawals
    >
);

const NOW_MILLISECONDS = Date.parse('2026-02-15T10:00:00Z');
const PAYMENT_CONFIRMED_AT = Date.parse('2026-02-15T08:00:00Z') / 1000;
const VALID_ISSUED_AT_VALUE = '2026-02-15T11:30';
const VALID_ISSUED_AT_EPOCH = Date.parse('2026-02-15T09:30:00Z') / 1000;
const VALID_MARK = '1234567890123456789';

function signedInAuth() {
    return {
        user: {
            id: 'admin-user',
            email: 'admin@example.com',
            name: 'Billing Admin',
            provider: 'local',
        },
        isLoading: false,
    };
}

function makeInvoice(
    overrides: Partial<BillingAdminPendingInvoice> = {},
): BillingAdminPendingInvoice {
    return {
        invoice_id: 'invoice-1',
        purchase_id: 'purchase-1',
        document_status: 'pending',
        purchase_status: 'fulfilled',
        provider: 'stripe',
        document_kind: 'receipt',
        refunded_amount_cents: 0,
        reversed_amount_cents: 0,
        reversed_credits: 0,
        dispute_active: false,
        requires_reversal_review: false,
        aade_document_type: null,
        aade_series: null,
        aade_aa: null,
        aade_mark: null,
        issued_at: null,
        recorded_at: null,
        created_at: PAYMENT_CONFIRMED_AT - 60,
        financial_retention_until: PAYMENT_CONFIRMED_AT + 315_360_000,
        package: {
            key: 'starter',
            credits: 100,
        },
        payment: {
            checkout_session_id: 'cs_test_minimum',
            payment_intent_id: 'pi_test_minimum',
            confirmed_at: PAYMENT_CONFIRMED_AT,
            livemode: false,
            amount_paid_cents: 1240,
            currency: 'eur',
            payment_status: 'paid',
        },
        customer: {
            name: 'Ada Example',
            email: 'ada@example.com',
            country: 'GR',
            city: 'Athens',
            postal_code: '10558',
            line1: '1 Example Street',
            line2: null,
            state: 'Attica',
            status: 'complete',
            missing_required_fields: [],
        },
        tax: {
            gross_amount_cents: 1240,
            net_amount_cents: 1000,
            vat_amount_cents: 240,
            vat_rate_percent: 24,
        },
        service: {
            code: 'GSUBS_CREDITS',
            name: 'GSUBS Credits',
        },
        ...overrides,
    };
}

function pendingResponse<T>(
    items: T[],
    nextCursor: string | null = null,
) {
    return {
        items,
        count: items.length,
        next_cursor: nextCursor,
    };
}

function makeRefundReview(): BillingAdminPendingRefund {
    return {
        reversal_id: 'r'.repeat(32),
        stripe_refund_id: 're_completed_refund',
        stripe_refund_status: 'succeeded',
        stripe_refund_created_at: PAYMENT_CONFIRMED_AT + 60,
        amount_cents: 1240,
        currency: 'eur',
        linked_withdrawal_id: 'w'.repeat(32),
        original_invoice: makeInvoice({
            invoice_id: 'i'.repeat(32),
            purchase_id: 'p'.repeat(32),
            purchase_status: 'refunded',
            refunded_amount_cents: 1240,
            reversed_amount_cents: 1240,
            requires_reversal_review: true,
        }),
    };
}

function makeWithdrawalReview(): BillingAdminPendingWithdrawal {
    return {
        withdrawal_id: 'w'.repeat(32),
        purchase_id: 'p'.repeat(32),
        locale: 'en',
        submitted_at: PAYMENT_CONFIRMED_AT + 30,
        contract_concluded_at: PAYMENT_CONFIRMED_AT,
        confirmed_name: 'Ada Example',
        confirmation_email: 'ada@example.com',
        available_adjustments: [],
    };
}

async function renderPendingInvoice(
    invoice: BillingAdminPendingInvoice = makeInvoice(),
) {
    listPendingInvoices.mockResolvedValueOnce(pendingResponse([invoice]));
    render(<BillingAdminPage />);
    await screen.findByTestId(
        `billing-admin-invoice-${invoice.invoice_id}`,
    );
}

type FormOverrides = {
    documentType?: string;
    series?: string;
    aa?: string;
    mark?: string;
    markRepeat?: string;
    issuedAt?: string;
    confirmed?: boolean;
};

function fillDocumentForm(overrides: FormOverrides = {}) {
    const values = {
        documentType: '11.2',
        series: '0',
        aa: '0042',
        mark: VALID_MARK,
        markRepeat: VALID_MARK,
        issuedAt: VALID_ISSUED_AT_VALUE,
        confirmed: true,
        ...overrides,
    };

    fireEvent.change(screen.getByLabelText('adminBillingDocumentType'), {
        target: { value: values.documentType },
    });
    fireEvent.change(screen.getByLabelText('adminBillingSeries'), {
        target: { value: values.series },
    });
    fireEvent.change(screen.getByLabelText('adminBillingAa'), {
        target: { value: values.aa },
    });
    fireEvent.change(screen.getByLabelText('adminBillingMark'), {
        target: { value: values.mark },
    });
    fireEvent.change(screen.getByLabelText('adminBillingMarkRepeat'), {
        target: { value: values.markRepeat },
    });
    fireEvent.change(screen.getByLabelText(/^adminBillingIssuedAt/), {
        target: { value: values.issuedAt },
    });
    if (values.confirmed) {
        fireEvent.click(
            screen.getByLabelText('adminBillingFinalDocumentConfirm'),
        );
    }
}

function submitDocumentForm() {
    fireEvent.click(screen.getByRole('button', {
        name: 'adminBillingRecord',
    }));
}

async function expectValidationAlert(message: string) {
    await waitFor(() => {
        expect(screen.getAllByRole('alert').some(
            (alert) => alert.textContent?.includes(message),
        )).toBe(true);
    });
}

describe('BillingAdminPage', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        jest.spyOn(Date, 'now').mockReturnValue(NOW_MILLISECONDS);
        mockUseAuth.mockReturnValue(signedInAuth());
        listPendingInvoices.mockResolvedValue(pendingResponse([]));
        listPendingRefunds.mockResolvedValue(pendingResponse([]));
        listPendingWithdrawals.mockResolvedValue(pendingResponse([]));
    });

    afterEach(() => {
        jest.restoreAllMocks();
    });

    it('waits for authentication without requesting the admin queue', () => {
        mockUseAuth.mockReturnValue({
            user: null,
            isLoading: true,
        });

        const { container } = render(<BillingAdminPage />);

        expect(container.querySelector('.animate-spin')).toBeInTheDocument();
        expect(listPendingInvoices).not.toHaveBeenCalled();
    });

    it('shows sign-in without requesting the queue when unauthenticated', async () => {
        mockUseAuth.mockReturnValue({
            user: null,
            isLoading: false,
        });

        render(<BillingAdminPage />);

        expect(
            await screen.findByText('adminBillingSignIn'),
        ).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'loginSubmit' }))
            .toHaveAttribute('href', '/login');
        expect(listPendingInvoices).not.toHaveBeenCalled();
    });

    it('renders the forbidden state only for a typed 403 API error', async () => {
        listPendingInvoices.mockRejectedValueOnce(
            new ApiError('Forbidden', 403),
        );

        render(<BillingAdminPage />);

        expect(
            await screen.findByRole('alert'),
        ).toHaveTextContent('adminBillingForbidden');
        expect(listPendingInvoices).toHaveBeenCalledTimes(1);
    });

    it('renders only the minimal typed reconciliation DTO', async () => {
        await renderPendingInvoice();

        expect(screen.getByText('GSUBS Credits')).toBeInTheDocument();
        expect(screen.getByText('cs_test_minimum')).toBeInTheDocument();
        expect(screen.getByText('pi_test_minimum')).toBeInTheDocument();
        expect(screen.getByText('Ada Example')).toBeInTheDocument();
        expect(screen.getByText('ada@example.com')).toBeInTheDocument();
        expect(screen.getByText(
            '1 Example Street, 10558 Athens, GR',
        )).toBeInTheDocument();
    });

    it('loads the independent refund and withdrawal review queues', async () => {
        listPendingRefunds.mockResolvedValueOnce(
            pendingResponse([makeRefundReview()]),
        );
        listPendingWithdrawals.mockResolvedValueOnce(
            pendingResponse([makeWithdrawalReview()]),
        );

        render(<BillingAdminPage />);

        expect(await screen.findByTestId(
            `billing-admin-refund-${'r'.repeat(32)}`,
        )).toBeInTheDocument();
        expect(screen.getByText('re_completed_refund')).toBeInTheDocument();
        expect(screen.getByTestId(
            `billing-admin-withdrawal-${'w'.repeat(32)}`,
        )).toBeInTheDocument();
        expect(listPendingInvoices).toHaveBeenCalledWith(undefined);
        expect(listPendingRefunds).toHaveBeenCalledWith();
        expect(listPendingWithdrawals).toHaveBeenCalledWith();
    });

    it('locks the verified MizAI document type and series defaults', async () => {
        await renderPendingInvoice();

        expect(screen.getByLabelText('adminBillingDocumentType'))
            .toHaveValue('11.2');
        expect(screen.getByLabelText('adminBillingDocumentType'))
            .toHaveAttribute('readonly');
        expect(screen.getByLabelText('adminBillingSeries'))
            .toHaveValue('0');
        expect(screen.getByLabelText('adminBillingSeries'))
            .toHaveAttribute('readonly');
        expect(screen.getByText('adminBillingMizaiBaseline'))
            .toBeInTheDocument();
    });

    it('locks initial recording when a reversal or dispute needs review', async () => {
        await renderPendingInvoice(makeInvoice({
            document_status: 'manual_review_required',
            dispute_active: true,
            requires_reversal_review: true,
        }));

        expect(screen.getByRole('alert')).toHaveTextContent(
            'adminBillingReversalWarning',
        );
        expect(screen.queryByRole('button', {
            name: 'adminBillingRecord',
        })).not.toBeInTheDocument();
    });

    it('shows an already-issued document as read-only', async () => {
        await renderPendingInvoice(makeInvoice({
            document_status: 'issued',
            aade_document_type: '11.2',
            aade_series: '0',
            aade_aa: '0041',
            aade_mark: '987654321',
            issued_at: VALID_ISSUED_AT_EPOCH,
        }));

        expect(screen.getByText('adminBillingIssuedReview'))
            .toBeInTheDocument();
        expect(screen.getByText('987654321')).toBeInTheDocument();
        expect(screen.queryByRole('button', {
            name: 'adminBillingRecord',
        })).not.toBeInTheDocument();
    });

    it('requires immutable payment proof before showing the form', async () => {
        await renderPendingInvoice(makeInvoice({
            payment: null,
        }));

        expect(screen.getByRole('alert')).toHaveTextContent(
            'adminBillingBeforePayment',
        );
        expect(screen.queryByRole('button', {
            name: 'adminBillingRecord',
        })).not.toBeInTheDocument();
    });

    it.each([
        {
            name: 'a non-canonical MARK',
            overrides: {
                mark: '0',
                markRepeat: '0',
            },
            message: 'adminBillingInvalidMark',
        },
        {
            name: 'different MARK entries',
            overrides: {
                markRepeat: '1234567890123456788',
            },
            message: 'adminBillingMarkMismatch',
        },
        {
            name: 'a nonexistent Athens daylight-saving time',
            overrides: {
                issuedAt: '2026-03-29T03:30',
            },
            message: 'adminBillingInvalidIssuedAt',
        },
        {
            name: 'an issue time before payment',
            overrides: {
                issuedAt: '2026-02-15T09:30',
            },
            message: 'adminBillingBeforePayment',
        },
        {
            name: 'a future issue time',
            overrides: {
                issuedAt: '2026-02-15T12:01',
            },
            message: 'adminBillingFutureIssuedAt',
        },
        {
            name: 'missing final-document confirmation',
            overrides: {
                confirmed: false,
            },
            message: 'adminBillingFinalDocumentConfirm',
        },
        {
            name: 'a non-AADE document type',
            overrides: {
                documentType: 'invoice',
            },
            message: 'adminBillingInvalidDocumentType',
        },
        {
            name: 'an unsupported series character',
            overrides: {
                series: 'GSUBS 2026!',
            },
            message: 'adminBillingInvalidSeries',
        },
        {
            name: 'a non-numeric sequential number',
            overrides: {
                aa: '42A',
            },
            message: 'adminBillingInvalidAa',
        },
    ])('rejects $name before any write', async ({ overrides, message }) => {
        await renderPendingInvoice();
        fillDocumentForm(overrides);

        submitDocumentForm();

        await expectValidationAlert(message);
        expect(recordIssuedDocument).not.toHaveBeenCalled();
    });

    it('submits one exact canonical payload and removes the recorded row', async () => {
        const recorded: RecordedAadeDocumentResponse = {
            invoice_id: 'invoice-1',
            purchase_id: 'purchase-1',
            document_status: 'issued',
            aade_document_type: '11.2',
            aade_series: '0',
            aade_aa: '0042',
            aade_mark: VALID_MARK,
            issued_at: VALID_ISSUED_AT_EPOCH,
            recorded_at: VALID_ISSUED_AT_EPOCH + 60,
            financial_retention_until: PAYMENT_CONFIRMED_AT + 315_360_000,
        };
        recordIssuedDocument.mockResolvedValueOnce(recorded);
        await renderPendingInvoice();
        fillDocumentForm();

        submitDocumentForm();

        await waitFor(() => {
            expect(recordIssuedDocument).toHaveBeenCalledTimes(1);
        });
        expect(recordIssuedDocument).toHaveBeenCalledWith('invoice-1', {
            document_type: '11.2',
            series: '0',
            aa: '0042',
            mark: VALID_MARK,
            issued_at: VALID_ISSUED_AT_EPOCH,
        });
        expect(await screen.findByRole('status')).toHaveTextContent(
            `recorded:${VALID_MARK}`,
        );
        expect(screen.queryByTestId('billing-admin-invoice-invoice-1'))
            .not.toBeInTheDocument();
    });

    it('reports a failed write once without retrying it automatically', async () => {
        recordIssuedDocument.mockRejectedValueOnce(
            new Error('Response lost after write'),
        );
        await renderPendingInvoice();
        fillDocumentForm();

        submitDocumentForm();

        await expectValidationAlert('adminBillingRecordError');
        expect(recordIssuedDocument).toHaveBeenCalledTimes(1);
        await Promise.resolve();
        await Promise.resolve();
        expect(recordIssuedDocument).toHaveBeenCalledTimes(1);
        expect(screen.getByTestId('billing-admin-invoice-invoice-1'))
            .toBeInTheDocument();
    });

    it('asks for a fresh sign-in when the admin write session is too old', async () => {
        recordIssuedDocument.mockRejectedValueOnce(
            new ApiError('Recent sign-in required', 403),
        );
        await renderPendingInvoice();
        fillDocumentForm();

        submitDocumentForm();

        await expectValidationAlert('adminBillingRecentSignInRequired');
        expect(recordIssuedDocument).toHaveBeenCalledTimes(1);
        expect(screen.getByTestId('billing-admin-invoice-invoice-1'))
            .toBeInTheDocument();
    });

    it('deduplicates appended pages and refreshes from the beginning', async () => {
        const firstInvoice = makeInvoice();
        const secondInvoice = makeInvoice({
            invoice_id: 'invoice-2',
            purchase_id: 'purchase-2',
        });
        const refreshedInvoice = makeInvoice({
            invoice_id: 'invoice-3',
            purchase_id: 'purchase-3',
        });
        listPendingInvoices
            .mockResolvedValueOnce(
                pendingResponse([firstInvoice], 'cursor-1'),
            )
            .mockResolvedValueOnce(
                pendingResponse([firstInvoice, secondInvoice]),
            )
            .mockResolvedValueOnce(
                pendingResponse([refreshedInvoice]),
            );

        render(<BillingAdminPage />);
        await screen.findByTestId('billing-admin-invoice-invoice-1');

        fireEvent.click(screen.getByRole('button', {
            name: 'adminBillingLoadMoreInvoices',
        }));

        await screen.findByTestId('billing-admin-invoice-invoice-2');
        expect(screen.getAllByTestId('billing-admin-invoice-invoice-1'))
            .toHaveLength(1);
        expect(listPendingInvoices).toHaveBeenNthCalledWith(1, undefined);
        expect(listPendingInvoices).toHaveBeenNthCalledWith(2, 'cursor-1');

        fireEvent.click(screen.getByRole('button', {
            name: 'adminBillingRefresh',
        }));

        await screen.findByTestId('billing-admin-invoice-invoice-3');
        expect(screen.queryByTestId('billing-admin-invoice-invoice-1'))
            .not.toBeInTheDocument();
        expect(screen.queryByTestId('billing-admin-invoice-invoice-2'))
            .not.toBeInTheDocument();
        expect(listPendingInvoices).toHaveBeenNthCalledWith(3, undefined);
    });
});
