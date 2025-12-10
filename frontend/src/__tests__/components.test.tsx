
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SubtitlePositionSelector } from '@/components/SubtitlePositionSelector';
import { VideoModal } from '@/components/VideoModal';
import { ViralIntelligence } from '@/components/ViralIntelligence';
import { AccountView } from '@/components/AccountView';
import { api } from '@/lib/api';

// Mocks
jest.mock('@/lib/api', () => ({
    api: {
        generateViralMetadata: jest.fn(),
        deleteAccount: jest.fn(),
    },
}));

jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({ t: (key: string) => key }),
}));

jest.mock('next/navigation', () => ({
    useRouter: () => ({ push: jest.fn() }),
}));

describe('Components Tests', () => {
    beforeEach(() => {
        jest.clearAllMocks();
    });

    describe('SubtitlePositionSelector', () => {
        it('should stop propagation on clicks', () => {
            const onChange = jest.fn();
            const onChangeLines = jest.fn();
            const parentClick = jest.fn();

            render(
                <div onClick={parentClick}>
                    <SubtitlePositionSelector
                        value="default" onChange={onChange}
                        lines={2} onChangeLines={onChangeLines}
                    />
                </div>
            );

            // Click option
            fireEvent.click(screen.getByText('Middle'));
            expect(onChange).toHaveBeenCalledWith('top');
            expect(parentClick).not.toHaveBeenCalled();

            // Click lines
            fireEvent.click(screen.getByText('1 Line'));
            expect(onChangeLines).toHaveBeenCalledWith(1);
            expect(parentClick).not.toHaveBeenCalled();
        });
    });

    describe('VideoModal', () => {
        it('should close on Escape', () => {
            const onClose = jest.fn();
            render(<VideoModal isOpen={true} onClose={onClose} videoUrl="test.mp4" />);

            fireEvent.keyDown(document, { key: 'Escape' });
            expect(onClose).toHaveBeenCalled();
        });

        it('should not close when clicking inside video container', () => {
            const onClose = jest.fn();
            render(<VideoModal isOpen={true} onClose={onClose} videoUrl="test.mp4" />);

            const container = screen.getByLabelText('Close video').closest('.video-container-glow');
            fireEvent.click(container!);
            expect(onClose).not.toHaveBeenCalled();

            // Clicking backdrop closes it
            fireEvent.click(screen.getByText(/Click outside/i).closest('.fixed')!);
            expect(onClose).toHaveBeenCalled();
        });
    });

    describe('ViralIntelligence', () => {
        it('should generate metadata and allow copying', async () => {
            const mockMeta = {
                hooks: ['Hook1'],
                caption_hook: 'CapHook',
                caption_body: 'Body',
                cta: 'CTA',
                hashtags: ['#tag']
            };
            (api.generateViralMetadata as jest.Mock).mockResolvedValue(mockMeta);

            // Mock clipboard
            Object.assign(navigator, {
                clipboard: {
                    writeText: jest.fn(),
                },
            });

            render(<ViralIntelligence jobId="job1" />);

            // Click generate
            fireEvent.click(screen.getByText('✨'));
            expect(screen.getByText('Analyzing transcript...')).toBeInTheDocument();

            // Wait for results
            await waitFor(() => expect(screen.getByText('Hook1')).toBeInTheDocument());

            // Test copy hook
            fireEvent.click(screen.getByText('Hook1'));
            expect(navigator.clipboard.writeText).toHaveBeenCalledWith('Hook1');

            // Test copy caption
            fireEvent.click(screen.getByText('Copy Full Caption'));
            const expectedCaption = `CapHook\n\nBody\n\nCTA\n\n#tag`;
            expect(navigator.clipboard.writeText).toHaveBeenCalledWith(expectedCaption);
        });

        it('should handle errors', async () => {
            (api.generateViralMetadata as jest.Mock).mockRejectedValue(new Error('Failed!'));
            render(<ViralIntelligence jobId="job1" />);

            fireEvent.click(screen.getByText('✨'));
            await waitFor(() => expect(screen.getByText('Failed!')).toBeInTheDocument());
        });
    });

    describe('AccountView', () => {
        const mockUser = { id: '1', name: 'User', email: 'test@test.com', provider: 'local' };

        it('should handle delete account flow', async () => {
            (api.deleteAccount as jest.Mock).mockResolvedValue({});

            render(
                <AccountView
                    user={mockUser}
                    onSaveProfile={jest.fn()}
                    accountMessage=""
                    accountError=""
                    accountSaving={false}
                />
            );

            // Click initial delete
            fireEvent.click(screen.getByRole('button', { name: 'deleteAccount' }));
            expect(screen.getByText('deleteAccountConfirm')).toBeInTheDocument();

            // Cancel
            fireEvent.click(screen.getByRole('button', { name: 'cancel' }));
            expect(screen.queryByText('deleteAccountConfirm')).not.toBeInTheDocument();

            // Click again and confirm
            fireEvent.click(screen.getByRole('button', { name: 'deleteAccount' }));
            fireEvent.click(screen.getByRole('button', { name: 'confirm' }));

            expect(screen.getByText('deleting')).toBeInTheDocument();
            await waitFor(() => expect(api.deleteAccount).toHaveBeenCalled());
        });

        it('should handle delete account error', async () => {
            (api.deleteAccount as jest.Mock).mockRejectedValue(new Error('Delete invalid'));

            render(
                <AccountView
                    user={mockUser}
                    onSaveProfile={jest.fn()}
                    accountMessage=""
                    accountError=""
                    accountSaving={false}
                />
            );

            fireEvent.click(screen.getByRole('button', { name: 'deleteAccount' }));
            fireEvent.click(screen.getByText('confirm'));

            await waitFor(() => expect(screen.getByText('Delete invalid')).toBeInTheDocument());
        });

        it('should handle profile update', async () => {
            const onSaveProfile = jest.fn();
            render(
                <AccountView
                    user={mockUser}
                    onSaveProfile={onSaveProfile}
                    accountMessage=""
                    accountError=""
                    accountSaving={false}
                />
            );

            // Change name
            fireEvent.change(screen.getByDisplayValue('User'), { target: { value: 'New User' } });

            // Change password
            const passwordInputs = screen.getAllByPlaceholderText('••••••••');
            fireEvent.change(passwordInputs[0], { target: { value: 'newpass' } });
            fireEvent.change(passwordInputs[1], { target: { value: 'newpass' } });

            // Save
            fireEvent.click(screen.getByText('saveChanges'));

            expect(onSaveProfile).toHaveBeenCalledWith({
                name: 'New User',
                password: 'newpass',
                confirmPassword: 'newpass'
            });
        });

        it('should disable inputs during saving', () => {
            render(
                <AccountView
                    user={mockUser}
                    onSaveProfile={jest.fn()}
                    accountMessage=""
                    accountError=""
                    accountSaving={true}
                />
            );

            expect(screen.getByDisplayValue('User')).toBeDisabled();
            expect(screen.getByText('saveChanges')).toBeDisabled();
        });
    });
});
