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
    const cancelButtonRef = useRef<HTMLButtonElement>(null);

    // Handle escape key to close modal
    const handleKeyDown = useCallback((e: KeyboardEvent) => {
        if (e.key === 'Escape') {
            onClose();
        }
    }, [onClose]);

    // Sync external systems only (DOM event listeners, body scroll)
    useEffect(() => {
        const previouslyFocused = document.activeElement instanceof HTMLElement
            ? document.activeElement
            : null;
        let focusTimer: ReturnType<typeof setTimeout> | undefined;

        if (isOpen) {
            document.addEventListener('keydown', handleKeyDown);
            document.body.style.overflow = 'hidden';
            // REGRESSION: focus the safe action so pressing Enter cannot discard
            // the current editing view by accident.
            focusTimer = setTimeout(() => cancelButtonRef.current?.focus(), 100);
        } else {
            document.removeEventListener('keydown', handleKeyDown);
            document.body.style.overflow = '';
        }
        return () => {
            if (focusTimer) clearTimeout(focusTimer);
            document.removeEventListener('keydown', handleKeyDown);
            document.body.style.overflow = '';
            previouslyFocused?.focus();
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
            className="fixed inset-0 z-50 flex items-center justify-center p-4 transition-all duration-200 cursor-pointer bg-black/55 backdrop-blur-sm"
            onClick={onClose}
        >
            {/* Modal Content */}
            <div
                className="relative max-w-sm w-full rounded-2xl border border-[var(--border)] bg-white shadow-2xl cursor-default animate-fade-in overflow-hidden"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Gradient accent at top */}
                <div className="absolute top-0 left-0 right-0 h-0.5 bg-[var(--accent)]" />

                {/* Content */}
                <div className="p-6 sm:p-8 text-center">
                    {/* Warning Icon */}
                    <div className="mx-auto mb-4 w-12 h-12 rounded-full bg-amber-500/10 border border-amber-500/20 flex items-center justify-center">
                        <svg className="w-6 h-6 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
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
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        {/* Cancel Button */}
                        <button
                            ref={cancelButtonRef}
                            onClick={onClose}
                            className="min-h-12 px-4 py-3 rounded-xl border border-[var(--border)] bg-white text-[var(--foreground)] font-medium hover:bg-[#f5f5f4] transition-colors duration-150"
                        >
                            {t('newVideoCancel') || 'Keep Working'}
                        </button>

                        {/* Confirm Button */}
                        <button
                            onClick={() => {
                                onConfirm();
                                onClose();
                            }}
                            className="min-h-12 px-4 py-3 rounded-xl bg-[var(--accent)] text-white font-semibold hover:bg-[#075be4] transition-colors duration-150"
                        >
                            {t('newVideoConfirm') || 'Start Fresh'}
                        </button>
                    </div>
                </div>

            </div>
        </div>
    );
}
