
import React, { useState, useEffect } from 'react';
import { useI18n } from '@/context/I18nContext';
import { User } from '@/context/AuthContext';

interface AccountViewProps {
    user: User;
    onSaveProfile: (name: string, password?: string, confirmPassword?: string) => Promise<void>;
    accountMessage: string;
    accountError: string;
    accountSaving: boolean;
}

export function AccountView({
    user,
    onSaveProfile,
    accountMessage,
    accountError,
    accountSaving,
}: AccountViewProps) {
    const { t } = useI18n();
    const [profileName, setProfileName] = useState(user.name);
    const [password, setPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');

    // Sync profile name if user updates from outside (optional, but good practice)
    useEffect(() => {
        setProfileName(user.name);
    }, [user.name]);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        await onSaveProfile(profileName, password, confirmPassword);
        if (!accountError) {
            setPassword('');
            setConfirmPassword('');
        }
    };

    return (
        <div className="flex flex-col gap-6 max-w-2xl mx-auto">
            <div className="card space-y-4">
                <div>
                    <p className="text-xs uppercase tracking-[0.28em] text-[var(--muted)]">{t('profileLabel')}</p>
                    <h2 className="text-2xl font-bold">{t('accountSettingsTitle')}</h2>
                    <p className="text-sm text-[var(--muted)]">{t('accountSettingsSubtitle')}</p>
                </div>
                <form className="space-y-4" onSubmit={handleSubmit}>
                    <div>
                        <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                            {t('displayNameLabel')}
                        </label>
                        <input
                            className="input-field"
                            value={profileName}
                            onChange={(e) => setProfileName(e.target.value)}
                        />
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                            {t('emailLabel')}
                        </label>
                        <input className="input-field" value={user.email} disabled />
                    </div>
                    {user.provider === 'local' && (
                        <>
                            <div>
                                <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                                    {t('newPasswordLabel')}
                                </label>
                                <input
                                    type="password"
                                    className="input-field"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    placeholder="••••••••"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                                    {t('confirmPasswordLabel')}
                                </label>
                                <input
                                    type="password"
                                    className="input-field"
                                    value={confirmPassword}
                                    onChange={(e) => setConfirmPassword(e.target.value)}
                                    placeholder="••••••••"
                                />
                            </div>
                        </>
                    )}

                    {accountMessage && (
                        <p className="text-[var(--accent)] text-sm">{accountMessage}</p>
                    )}
                    {accountError && (
                        <p className="text-[var(--danger)] text-sm">{accountError}</p>
                    )}

                    <div className="pt-4">
                        <button
                            type="submit"
                            disabled={accountSaving}
                            className="btn-primary w-full sm:w-auto"
                        >
                            {accountSaving ? t('saving') : t('saveChanges')}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
