import React from 'react';
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import RegisterPage from '@/app/register/page';

jest.mock('@/context/AuthContext', () => ({
    useAuth: () => ({ register: jest.fn() }),
}));

jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({ t: (key: string) => key }),
}));

jest.mock('next/navigation', () => ({
    useRouter: () => ({ push: jest.fn() }),
}));

describe('RegisterPage', () => {
    it('uses the canonical gsubs identity', () => {
        render(<RegisterPage />);

        const homeLink = screen.getByRole('link', { name: 'brandHomeLabel' });
        expect(within(homeLink).getByRole('img', { name: 'gsubs' }))
            .toHaveAttribute('src', '/brand/gsubs-logo.svg');
        expect(screen.getByText('gsubs')).toBeInTheDocument();
        expect(screen.getByText('registerTitle')).toBeInTheDocument();
    });
});
