import { useCallback, useEffect, useId, useRef } from 'react';
import { useDocumentScrollLock } from '@/hooks/useDocumentScrollLock';

interface ConfirmActionModalProps {
    isOpen: boolean;
    title: string;
    description: string;
    cancelLabel: string;
    confirmLabel: string;
    onClose: () => void;
    onConfirm: () => void;
}

export function ConfirmActionModal({
    isOpen,
    title,
    description,
    cancelLabel,
    confirmLabel,
    onClose,
    onConfirm,
}: ConfirmActionModalProps) {
    const modalId = useId();
    const cancelButtonRef = useRef<HTMLButtonElement>(null);
    const onCloseRef = useRef(onClose);

    useDocumentScrollLock(isOpen);

    useEffect(() => {
        onCloseRef.current = onClose;
    }, [onClose]);

    const handleKeyDown = useCallback((event: KeyboardEvent) => {
        if (event.key !== 'Escape') return;
        event.preventDefault();
        onCloseRef.current();
    }, []);

    useEffect(() => {
        if (!isOpen) return;

        const previouslyFocused = document.activeElement instanceof HTMLElement
            ? document.activeElement
            : null;
        document.addEventListener('keydown', handleKeyDown);
        const focusTimer = window.setTimeout(() => cancelButtonRef.current?.focus(), 100);

        return () => {
            window.clearTimeout(focusTimer);
            document.removeEventListener('keydown', handleKeyDown);
            previouslyFocused?.focus();
        };
    }, [handleKeyDown, isOpen]);

    if (!isOpen) return null;

    const titleId = `${modalId}-title`;
    const descriptionId = `${modalId}-description`;

    return (
        <div
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            aria-describedby={descriptionId}
            className="fixed inset-0 z-50 flex cursor-pointer items-center justify-center bg-black/55 p-4 backdrop-blur-sm transition-all duration-200"
            onClick={onClose}
        >
            <div
                className="relative w-full max-w-sm cursor-default overflow-hidden rounded-2xl border border-[var(--border)] bg-white shadow-2xl animate-fade-in"
                onClick={(event) => event.stopPropagation()}
            >
                <div className="absolute inset-x-0 top-0 h-0.5 bg-[var(--accent)]" />

                <div className="p-6 text-center sm:p-8">
                    <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full border border-amber-500/20 bg-amber-500/10">
                        <svg
                            className="h-6 w-6 text-amber-500"
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke="currentColor"
                            aria-hidden="true"
                        >
                            <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={2}
                                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                            />
                        </svg>
                    </div>

                    <h2
                        id={titleId}
                        className="mb-2 text-xl font-bold text-[var(--foreground)]"
                    >
                        {title}
                    </h2>
                    <p
                        id={descriptionId}
                        className="mb-6 text-sm leading-relaxed text-[var(--muted)]"
                    >
                        {description}
                    </p>

                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                        <button
                            ref={cancelButtonRef}
                            type="button"
                            onClick={onClose}
                            className="min-h-12 rounded-xl border border-[var(--border)] bg-white px-4 py-3 font-medium text-[var(--foreground)] transition-colors duration-150 hover:bg-[#f5f5f4]"
                        >
                            {cancelLabel}
                        </button>
                        <button
                            type="button"
                            onClick={() => {
                                onConfirm();
                                onClose();
                            }}
                            className="min-h-12 rounded-xl bg-[var(--accent)] px-4 py-3 font-semibold text-white transition-colors duration-150 hover:bg-[#075be4]"
                        >
                            {confirmLabel}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
