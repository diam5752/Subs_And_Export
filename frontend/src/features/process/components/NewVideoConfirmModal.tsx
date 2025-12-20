import React, { useEffect, useCallback, useRef } from 'react';
import { useI18n } from '@/context/I18nContext';

interface NewVideoConfirmModalProps {
    isOpen: boolean;
    onClose: () => void;
    onConfirm: () => void;
}

export function NewVideoConfirmModal({ isOpen, onClose, onConfirm }: NewVideoConfirmModalProps) {
    const { t } = useI18n();
    const containerRef = useRef<HTMLDivElement>(null);
    const confirmButtonRef = useRef<HTMLButtonElement>(null);

    // Handle escape key to close modal
    const handleKeyDown = useCallback((e: KeyboardEvent) => {
        if (e.key === 'Escape') {
            onClose();
        }
    }, [onClose]);

    // Sync external systems only (DOM event listeners, body scroll)
    useEffect(() => {
        if (isOpen) {
            document.addEventListener('keydown', handleKeyDown);
            document.body.style.overflow = 'hidden';
            // Focus the confirm button for accessibility
            setTimeout(() => confirmButtonRef.current?.focus(), 100);
        } else {
            document.removeEventListener('keydown', handleKeyDown);
            document.body.style.overflow = '';
        }
        return () => {
            document.removeEventListener('keydown', handleKeyDown);
            document.body.style.overflow = '';
        };
    }, [isOpen, handleKeyDown]);

    if (!isOpen) return null;

    return (
        <div
            ref={containerRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="new-video-modal-title"
            aria-describedby="new-video-modal-desc"
            className="fixed inset-0 z-50 flex items-center justify-center p-4 transition-all duration-300 ease-out cursor-pointer bg-black/80 backdrop-blur-xl"
            onClick={onClose}
        >
            {/* Modal Content */}
            <div
                className="relative max-w-md w-full rounded-2xl border border-white/10 bg-[var(--surface-elevated)] shadow-2xl cursor-default animate-fade-in overflow-hidden"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Gradient accent at top */}
                <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-[var(--accent)] via-[var(--accent-secondary)] to-[var(--accent)]" />

                {/* Content */}
                <div className="p-6 text-center">
                    {/* Warning Icon */}
                    <div className="mx-auto mb-4 w-16 h-16 rounded-full bg-amber-500/10 border border-amber-500/20 flex items-center justify-center">
                        <svg className="w-8 h-8 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                        </svg>
                    </div>

                    {/* Title */}
                    <h3
                        id="new-video-modal-title"
                        className="text-xl font-bold text-[var(--foreground)] mb-2"
                    >
                        {t('newVideoModalTitle') || 'Start a new project?'}
                    </h3>

                    {/* Description */}
                    <p
                        id="new-video-modal-desc"
                        className="text-sm text-[var(--muted)] mb-6 leading-relaxed"
                    >
                        {t('newVideoModalDesc') || 'Your current video and all edits will be discarded. This action cannot be undone.'}
                    </p>

                    {/* Actions */}
                    <div className="flex gap-3">
                        {/* Cancel Button */}
                        <button
                            onClick={onClose}
                            className="flex-1 px-4 py-3 rounded-xl border border-white/10 bg-white/5 text-[var(--foreground)] font-medium hover:bg-white/10 transition-all duration-200"
                        >
                            {t('newVideoCancel') || 'Keep Working'}
                        </button>

                        {/* Confirm Button */}
                        <button
                            ref={confirmButtonRef}
                            onClick={() => {
                                onConfirm();
                                onClose();
                            }}
                            className="flex-1 px-4 py-3 rounded-xl bg-gradient-to-r from-[var(--accent)] to-[var(--accent-secondary)] text-white font-semibold hover:opacity-90 transition-all duration-200 shadow-lg shadow-[var(--accent)]/20"
                        >
                            {t('newVideoConfirm') || 'Start Fresh'}
                        </button>
                    </div>
                </div>

                {/* Hint at bottom */}
                <div className="px-6 py-3 border-t border-white/5 bg-white/[0.02]">
                    <p className="text-xs text-center text-[var(--muted)]/60">
                        Press <kbd className="px-1.5 py-0.5 mx-1 rounded bg-white/10 text-white/50 text-[10px] font-mono">ESC</kbd> to cancel
                    </p>
                </div>
            </div>
        </div>
    );
}
