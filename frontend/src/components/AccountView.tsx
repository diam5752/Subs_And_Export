
import React, { useState, useEffect } from 'react';
import { useI18n } from '@/context/I18nContext';
import { User } from '@/context/AuthContext';
import { api, JobResponse } from '@/lib/api';
import { useRouter } from 'next/navigation';
import { RecentJobsList } from './RecentJobsList';

interface AccountViewProps {
    user: User;
    onSaveProfile: (name: string, password?: string, confirmPassword?: string) => Promise<void>;
    onLogout: () => void;
    accountMessage: string;
    accountError: string;
    accountSaving: boolean;
    activeTab?: 'profile' | 'history';
    // History props
    recentJobs?: JobResponse[];
    jobsLoading?: boolean;
    onJobSelect?: (job: JobResponse | null) => void;
    selectedJobId?: string | undefined;
    onRefreshJobs?: () => Promise<void>;
    formatDate?: (ts: number | string) => string;
    buildStaticUrl?: (path?: string | null) => string | null;
    setShowPreview?: (show: boolean) => void;
    currentPage?: number;
    totalPages?: number;
    onNextPage?: () => void;
    onPrevPage?: () => void;
    totalJobs?: number;
    pageSize?: number;
}

export function AccountView({
    user,
    onSaveProfile,
    onLogout,
    accountMessage,
    accountError,
    accountSaving,
    activeTab = 'profile',
    recentJobs = [],
    jobsLoading = false,
    onJobSelect = () => { },
    selectedJobId,
    onRefreshJobs = async () => { },
    formatDate = () => '',
    buildStaticUrl = () => null,
    setShowPreview = () => { },
    currentPage = 1,
    totalPages = 1,
    onNextPage = () => { },
    onPrevPage = () => { },
    totalJobs = 0,
    pageSize = 5,
}: AccountViewProps) {
    const { t } = useI18n();
    const router = useRouter();
    // Use user.name as key to reset state when user changes - avoids setState in effect
    const [profileName, setProfileName] = useState(user.name);
    const [password, setPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
    const [deleting, setDeleting] = useState(false);
    const [deleteError, setDeleteError] = useState('');

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        await onSaveProfile(profileName, password, confirmPassword);
        if (!accountError) {
            setPassword('');
            setConfirmPassword('');
        }
    };

    const handleDeleteAccount = async () => {
        setDeleting(true);
        setDeleteError('');
        try {
            await api.deleteAccount();
            router.push('/login');
        } catch (err) {
            setDeleteError(err instanceof Error ? err.message : t('deleteAccountError'));
            setDeleting(false);
        }
    };

    if (activeTab === 'history') {
        return (
            <div className="flex flex-col gap-6 max-w-4xl mx-auto">
                <div className="space-y-4">
                    <div>
                        <p className="text-xs uppercase tracking-[0.28em] text-[var(--muted)]">{t('historyTitle') || 'HISTORY'}</p>
                        <h2 className="text-2xl font-bold">{t('pastGenerations') || 'Past Generations'}</h2>
                        <p className="text-sm text-[var(--muted)]">{t('historySubtitle') || 'View and manage your processed videos.'}</p>
                    </div>

                    <RecentJobsList
                        jobs={recentJobs}
                        isLoading={jobsLoading}
                        onJobSelect={onJobSelect}
                        selectedJobId={selectedJobId}
                        onRefreshJobs={onRefreshJobs}
                        formatDate={formatDate}
                        buildStaticUrl={buildStaticUrl}
                        setShowPreview={setShowPreview}
                        currentPage={currentPage}
                        totalPages={totalPages}
                        onNextPage={onNextPage}
                        onPrevPage={onPrevPage}
                        totalJobs={totalJobs}
                        pageSize={pageSize}
                    />
                </div>
            </div>
        );
    }

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

                    <div className="pt-4 flex items-center justify-between">
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

            {/* Sign Out Button - iOS Style */}
            <div className="card p-1">
                <button
                    onClick={onLogout}
                    className="w-full py-3.5 text-[var(--danger)] font-medium text-base hover:bg-[var(--danger)]/5 rounded-xl transition-colors flex items-center justify-center gap-2"
                >
                    {t('signOut')}
                </button>
            </div>

            {/* Danger Zone */}
            <div className="card border-[var(--danger)]/30 space-y-4">
                <div>
                    <p className="text-xs uppercase tracking-[0.28em] text-[var(--danger)]">{t('dangerZone')}</p>
                    <h3 className="text-lg font-semibold text-[var(--danger)]">{t('deleteAccount')}</h3>
                    <p className="text-sm text-[var(--muted)]">{t('deleteAccountDescription')}</p>
                </div>

                {deleteError && (
                    <p className="text-[var(--danger)] text-sm">{deleteError}</p>
                )}

                {!showDeleteConfirm ? (
                    <button
                        onClick={() => setShowDeleteConfirm(true)}
                        className="px-4 py-2 rounded-lg border border-[var(--danger)]/50 text-[var(--danger)] hover:bg-[var(--danger)]/10 transition-colors"
                    >
                        {t('deleteAccount')}
                    </button>
                ) : (
                    <div className="bg-[var(--danger)]/10 border border-[var(--danger)]/30 rounded-xl p-4 space-y-3">
                        <p className="text-sm font-medium">{t('deleteAccountConfirm')}</p>
                        <div className="flex gap-3">
                            <button
                                onClick={handleDeleteAccount}
                                disabled={deleting}
                                className="px-4 py-2 rounded-lg bg-[var(--danger)] text-white font-medium hover:bg-[var(--danger)]/90 transition-colors disabled:opacity-50"
                            >
                                {deleting ? t('deleting') : t('confirm')}
                            </button>
                            <button
                                onClick={() => setShowDeleteConfirm(false)}
                                disabled={deleting}
                                className="px-4 py-2 rounded-lg border border-[var(--border)] hover:bg-white/5 transition-colors"
                            >
                                {t('cancel')}
                            </button>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
