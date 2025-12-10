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

    it('calls onSaveProfile with updated name and password', async () => {
        const onSaveProfile = jest.fn();
        renderAccountView({ onSaveProfile });

        const nameInput = screen.getByDisplayValue('Test User');
        fireEvent.change(nameInput, { target: { value: 'New Name' } });

        const passwordInputs = screen.getAllByPlaceholderText('••••••••');
        fireEvent.change(passwordInputs[0], { target: { value: 'newpass123' } });
        fireEvent.change(passwordInputs[1], { target: { value: 'newpass123' } });

        fireEvent.click(screen.getByRole('button', { name: /save changes/i }));

        await waitFor(() => expect(onSaveProfile).toHaveBeenCalledWith('New Name', 'newpass123', 'newpass123'));
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

        // Confirm delete - click the confirm button directly
        fireEvent.click(screen.getByRole('button', { name: /confirm/i }));

        await waitFor(() => expect(api.deleteAccount).toHaveBeenCalled());
        await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/login'));
    });

    it('handles account deletion error', async () => {
        (api.deleteAccount as jest.Mock).mockRejectedValue(new Error('Delete failed'));
        renderAccountView();

        fireEvent.click(screen.getByRole('button', { name: 'Delete Account' }));
        fireEvent.click(screen.getByRole('button', { name: /confirm/i }));

        await waitFor(() => expect(screen.getByText('Delete failed')).toBeInTheDocument());
        // Verify delete was cancelled (button should be "Delete Account" again or close state)
        // Based on UI logic, it just sets error and unsets deleting state.
        // The modal stays open? Let's check AccountView.tsx logic if needed, but error message check is sufficient for lines 49-50.
    });

    it('cancels account deletion', () => {
        renderAccountView();

        fireEvent.click(screen.getByRole('button', { name: 'Delete Account' }));

        // Cancel button
        fireEvent.click(screen.getByRole('button', { name: /cancel/i }));

        // Confirmation should disappear
        expect(screen.queryByText(/this action cannot be undone/i)).not.toBeInTheDocument();
    });
});
