import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { CreditsBadge } from '@/components/CreditsBadge';
import { Spinner } from '@/components/Spinner';

let mockPointsState = {
    balance: 1234 as number | null,
    isLoading: false,
    error: null as string | null,
};
let mockMissingCreditsTranslations = false;

jest.mock('@/context/I18nContext', () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const en = require('@/i18n/en.json');
    return {
        useI18n: () => ({
            t: (key: string) => mockMissingCreditsTranslations ? '' : (en[key] ?? key),
        }),
    };
});

jest.mock('@/context/PointsContext', () => ({
    __esModule: true,
    ...(() => {
        const refreshBalanceMock = jest.fn();
        return {
            usePoints: () => ({
                ...mockPointsState,
                refreshBalance: refreshBalanceMock,
                setBalance: jest.fn(),
            }),
            __refreshBalanceMock: refreshBalanceMock,
        };
    })(),
}));

describe('CreditsBadge', () => {
    const { __refreshBalanceMock } = jest.requireMock('@/context/PointsContext') as {
        __refreshBalanceMock: jest.Mock;
    };

    beforeEach(() => {
        jest.clearAllMocks();
        mockPointsState = { balance: 1234, isLoading: false, error: null };
        mockMissingCreditsTranslations = false;
    });

    it('renders the real balance with the MizAI coin mark and refreshes on click', () => {
        render(<CreditsBadge />);

        expect(screen.getByText('1,234')).toBeInTheDocument();
        expect(screen.getByTestId('credits-coin-icon')).toBeInTheDocument();

        fireEvent.click(screen.getByRole('button', { name: 'Credits: 1,234' }));
        expect(__refreshBalanceMock).toHaveBeenCalled();
    });

    it('shows unavailable/loading state and delegates purchase clicks', () => {
        const onClick = jest.fn();
        mockPointsState = { balance: null, isLoading: true, error: 'offline' };
        mockMissingCreditsTranslations = true;

        render(<CreditsBadge onClick={onClick} />);

        const button = screen.getByRole('button', { name: 'Credits: —' });
        expect(button).toHaveAttribute('aria-busy', 'true');
        expect(button).toHaveAttribute('title', 'Unavailable');
        expect(screen.getByText('+')).toBeInTheDocument();
        fireEvent.click(button);
        expect(onClick).toHaveBeenCalledTimes(1);
        expect(__refreshBalanceMock).not.toHaveBeenCalled();
    });

    it('uses the spinner default size when no class is supplied', () => {
        const { container } = render(<Spinner />);
        expect(container.querySelector('svg')).toHaveClass('w-5', 'h-5', 'text-current');
    });
});
