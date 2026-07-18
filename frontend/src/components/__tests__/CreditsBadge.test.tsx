import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { CreditsBadge } from '@/components/CreditsBadge';

jest.mock('@/context/I18nContext', () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const en = require('@/i18n/en.json');
    return {
        useI18n: () => ({ t: (key: string) => en[key] ?? key }),
    };
});

jest.mock('@/context/PointsContext', () => ({
    __esModule: true,
    ...(() => {
        const refreshBalanceMock = jest.fn();
        return {
            usePoints: () => ({
                balance: 1234,
                isLoading: false,
                error: null,
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
    });

    it('renders the real balance with the MizAI coin mark and refreshes on click', () => {
        render(<CreditsBadge />);

        expect(screen.getByText('1,234')).toBeInTheDocument();
        expect(screen.getByTestId('credits-coin-icon')).toBeInTheDocument();

        fireEvent.click(screen.getByRole('button', { name: 'Credits: 1,234' }));
        expect(__refreshBalanceMock).toHaveBeenCalled();
    });
});
