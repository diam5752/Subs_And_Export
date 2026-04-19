import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { PointsProvider, usePoints } from '@/context/PointsContext';
import { api } from '@/lib/api';
import { useAuth } from '@/context/AuthContext';

jest.mock('@/lib/api', () => ({
    api: {
        getPointsBalance: jest.fn(),
    },
}));

jest.mock('@/context/AuthContext', () => ({
    useAuth: jest.fn(),
}));

function PointsHarness() {
    const { balance, isLoading, error, refreshBalance, setBalance } = usePoints();

    return (
        <div>
            <div data-testid="balance">{balance === null ? 'null' : String(balance)}</div>
            <div data-testid="loading">{String(isLoading)}</div>
            <div data-testid="error">{error ?? 'none'}</div>
            <button type="button" onClick={() => void refreshBalance()}>
                refresh-balance
            </button>
            <button type="button" onClick={() => setBalance(123)}>
                set-balance
            </button>
        </div>
    );
}

describe('PointsContext', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        (useAuth as jest.Mock).mockReturnValue({
            user: { id: 'u1', email: 'user@example.com' },
            isLoading: false,
        });
        (api.getPointsBalance as jest.Mock).mockResolvedValue({ balance: 42 });
    });

    it('loads the balance for authenticated users', async () => {
        render(
            <PointsProvider>
                <PointsHarness />
            </PointsProvider>,
        );

        await waitFor(() => {
            expect(api.getPointsBalance).toHaveBeenCalled();
            expect(screen.getByTestId('balance')).toHaveTextContent('42');
            expect(screen.getByTestId('loading')).toHaveTextContent('false');
        });
    });

    it('resets state without calling the API when no user is present', async () => {
        (useAuth as jest.Mock).mockReturnValue({
            user: null,
            isLoading: false,
        });

        render(
            <PointsProvider>
                <PointsHarness />
            </PointsProvider>,
        );

        await waitFor(() => {
            expect(api.getPointsBalance).not.toHaveBeenCalled();
            expect(screen.getByTestId('balance')).toHaveTextContent('null');
            expect(screen.getByTestId('error')).toHaveTextContent('none');
        });
    });

    it('waits for auth loading before fetching', async () => {
        (useAuth as jest.Mock).mockReturnValue({
            user: { id: 'u1' },
            isLoading: true,
        });

        render(
            <PointsProvider>
                <PointsHarness />
            </PointsProvider>,
        );

        await waitFor(() => {
            expect(api.getPointsBalance).not.toHaveBeenCalled();
            expect(screen.getByTestId('balance')).toHaveTextContent('null');
        });
    });

    it('surfaces API errors and allows manual retry', async () => {
        (api.getPointsBalance as jest.Mock)
            .mockRejectedValueOnce(new Error('balance failed'))
            .mockResolvedValueOnce({ balance: 77 });

        render(
            <PointsProvider>
                <PointsHarness />
            </PointsProvider>,
        );

        await waitFor(() => {
            expect(screen.getByTestId('error')).toHaveTextContent('balance failed');
        });

        fireEvent.click(screen.getByRole('button', { name: 'refresh-balance' }));

        await waitFor(() => {
            expect(screen.getByTestId('balance')).toHaveTextContent('77');
            expect(screen.getByTestId('error')).toHaveTextContent('none');
        });
    });

    it('exposes setBalance for local optimistic updates', async () => {
        render(
            <PointsProvider>
                <PointsHarness />
            </PointsProvider>,
        );

        await waitFor(() => expect(screen.getByTestId('balance')).toHaveTextContent('42'));

        fireEvent.click(screen.getByRole('button', { name: 'set-balance' }));

        expect(screen.getByTestId('balance')).toHaveTextContent('123');
    });

    it('throws when usePoints is called outside a provider', () => {
        expect(() => render(<PointsHarness />)).toThrow('usePoints must be used within a PointsProvider');
    });
});
