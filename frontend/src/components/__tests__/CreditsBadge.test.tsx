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

    it('renders balance, refreshes on click, and shows pricing tooltip', () => {
        render(<CreditsBadge />);

        expect(screen.getByText('1,234')).toBeInTheDocument();

        fireEvent.click(screen.getByRole('button', { name: 'Refresh credits' }));
        expect(__refreshBalanceMock).toHaveBeenCalled();

        const pricingButton = screen.getByRole('button', { name: 'Points pricing' });
        fireEvent.mouseEnter(pricingButton);

        expect(screen.getAllByText('Points pricing').length).toBeGreaterThan(0);
        expect(screen.getByText('Video processing (Standard)')).toBeInTheDocument();
        expect(screen.getByText('Video processing (Pro)')).toBeInTheDocument();
        expect(screen.getByText('Fact check')).toBeInTheDocument();
    });
});
