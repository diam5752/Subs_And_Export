import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { AccountView } from '../AccountView';
import { I18nProvider } from '@/context/I18nContext';

// Mock Next.js router
const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
    useRouter: () => ({ push: mockPush }),
}));

// Mock API
jest.mock('@/lib/api', () => ({
    api: {
        deleteAccount: jest.fn(),
    },
}));

import { api } from '@/lib/api';

const mockUser = {
    id: '123',
    name: 'Test User',
    email: 'test@example.com',
    provider: 'local',
};

const renderAccountView = (props: Partial<React.ComponentProps<typeof AccountView>> = {}) => {
    return render(
        <I18nProvider initialLocale="en">
            <AccountView
                user={mockUser}
                onSaveProfile={jest.fn()}
                accountMessage=""
                accountError=""
                accountSaving={false}
                {...props}
            />
        </I18nProvider>
    );
};

describe('AccountView', () => {
    beforeEach(() => {
        jest.clearAllMocks();
    });

    it('renders user details correctly', () => {
        renderAccountView();
        expect(screen.getByDisplayValue('Test User')).toBeInTheDocument();
        expect(screen.getByDisplayValue('test@example.com')).toBeInTheDocument();
    });

    it('calls onSaveProfile with updated name', () => {
        const onSaveProfile = jest.fn();
        renderAccountView({ onSaveProfile });

        const nameInput = screen.getByDisplayValue('Test User');
        fireEvent.change(nameInput, { target: { value: 'New Name' } });

        fireEvent.click(screen.getByRole('button', { name: /save changes/i }));

        expect(onSaveProfile).toHaveBeenCalledWith('New Name', '', '');
    });

    it('renders password fields only for local provider', () => {
        const { rerender } = renderAccountView({ user: { ...mockUser, provider: 'local' } });
        expect(screen.getByText(/new password/i)).toBeInTheDocument();

        rerender(
            <I18nProvider initialLocale="en">
                <AccountView
                    user={{ ...mockUser, provider: 'google' }}
                    onSaveProfile={jest.fn()}
                    accountMessage=""
                    accountError=""
                    accountSaving={false}
                />
            </I18nProvider>
        );
        expect(screen.queryByText(/new password/i)).not.toBeInTheDocument();
    });

    it('handles account deletion flow', async () => {
        (api.deleteAccount as jest.Mock).mockResolvedValue(undefined);
        renderAccountView();

        // Initial delete button shows confirmation
        fireEvent.click(screen.getByRole('button', { name: 'Delete Account' }));
        expect(screen.getByText(/this action cannot be undone/i)).toBeInTheDocument();

        // Confirm delete
        const confirmBtn = screen.getByRole('button', { name: /confirm/i });
        // Use more specific selector if multiple buttons have similar text, 
        // but here the red delete button appears in the confirm zone.
        // Actually, the button text is "Confirm" in the code: {t('confirm')}
        // Let's verify translation or props. In AccountView code: {deleting ? t('deleting') : t('confirm')}
        // I18nContext default mock might return key or simple English. 

        // Let's look at AccountView structure:
        // Inside confirmation: <button ...>{t('confirm')}</button>
        // Depending on I18n mock, it usually returns the key or a stub. 
        // The I18nProvider in tests likely uses the real simple en dictionary or identity.
        // Assuming 'confirm' key translates to 'Confirm'.

        // Wait, the I18nContext mock in dashboard tests suggests it uses keys or real phrases.
        // Let's check `src/context/I18nContext.tsx` or assume standard keys. 
        // In AccountView.tsx: `t('confirm')`

        // Let's try to find by text 'Confirm' or check the implementation of I18nContext if needed.
        // Safe bet: The Confirm button is red (bg-[var(--danger)]).

        const confirmButton = screen.getByRole('button', { name: /confirm/i });
        fireEvent.click(confirmButton);

        await waitFor(() => expect(api.deleteAccount).toHaveBeenCalled());
        await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/login'));
    });
});
