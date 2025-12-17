import React, { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

export interface InfoTooltipProps {
    ariaLabel: string;
    children: React.ReactNode;
}

export function InfoTooltip({ ariaLabel, children }: InfoTooltipProps) {
    const tooltipId = useId();
    const anchorRef = useRef<HTMLButtonElement>(null);
    const tooltipRef = useRef<HTMLDivElement>(null);
    const [hovered, setHovered] = useState(false);
    const [focused, setFocused] = useState(false);
    const open = hovered || focused;

    const [layout, setLayout] = useState<{
        top: number;
        left: number;
        placement: 'top' | 'bottom';
        arrowLeft: number;
    } | null>(null);

    const updateLayout = useCallback(() => {
        const anchorEl = anchorRef.current;
        const tooltipEl = tooltipRef.current;
        if (!anchorEl || !tooltipEl) return;

        const margin = 12;
        const gap = 8;
        const anchorRect = anchorEl.getBoundingClientRect();
        const tooltipRect = tooltipEl.getBoundingClientRect();

        const anchorCenterX = anchorRect.left + anchorRect.width / 2;

        let placement: 'top' | 'bottom' = 'bottom';
        let top = anchorRect.bottom + gap;

        if (top + tooltipRect.height + margin > window.innerHeight) {
            const candidateTop = anchorRect.top - gap - tooltipRect.height;
            if (candidateTop >= margin) {
                placement = 'top';
                top = candidateTop;
            }
        }

        // We position by center, then clamp within viewport so it never gets clipped.
        const halfWidth = tooltipRect.width / 2;
        const minCenterX = margin + halfWidth;
        const maxCenterX = window.innerWidth - margin - halfWidth;
        const clampedCenterX = Math.min(Math.max(anchorCenterX, minCenterX), maxCenterX);

        // Arrow should still point at the anchor's center, even when the tooltip is clamped.
        const tooltipLeftEdge = clampedCenterX - halfWidth;
        const unclampedArrowLeft = anchorCenterX - tooltipLeftEdge;
        const arrowPadding = 14;
        const arrowLeft = Math.min(
            Math.max(unclampedArrowLeft, arrowPadding),
            Math.max(arrowPadding, tooltipRect.width - arrowPadding),
        );

        setLayout({ top, left: clampedCenterX, placement, arrowLeft });
    }, []);

    useLayoutEffect(() => {
        if (!open) return;
        updateLayout();
    }, [open, updateLayout]);

    useEffect(() => {
        if (!open) return;

        const handleWindowChange = () => updateLayout();
        window.addEventListener('resize', handleWindowChange);
        window.addEventListener('scroll', handleWindowChange, true);

        const tooltipEl = tooltipRef.current;
        if (!tooltipEl || typeof ResizeObserver === 'undefined') {
            return () => {
                window.removeEventListener('resize', handleWindowChange);
                window.removeEventListener('scroll', handleWindowChange, true);
            };
        }

        const observer = new ResizeObserver(() => updateLayout());
        observer.observe(tooltipEl);

        return () => {
            observer.disconnect();
            window.removeEventListener('resize', handleWindowChange);
            window.removeEventListener('scroll', handleWindowChange, true);
        };
    }, [open, updateLayout]);

    return (
        <span className="relative inline-flex shrink-0">
            <button
                ref={anchorRef}
                type="button"
                aria-label={ariaLabel}
                aria-describedby={open ? tooltipId : undefined}
                onMouseEnter={() => setHovered(true)}
                onMouseLeave={(e) => {
                    const nextTarget = e.relatedTarget as Node | null;
                    if (nextTarget && tooltipRef.current?.contains(nextTarget)) return;
                    setHovered(false);
                }}
                onFocus={() => setFocused(true)}
                onBlur={() => setFocused(false)}
                onKeyDown={(e) => {
                    if (e.key !== 'Escape') return;
                    e.stopPropagation();
                    setHovered(false);
                    setFocused(false);
                }}
                className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--muted)] transition-colors hover:border-[var(--accent)]/40 hover:text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/40"
            >
                <svg
                    aria-hidden="true"
                    className="h-3.5 w-3.5"
                    viewBox="0 0 20 20"
                    fill="none"
                >
                    <circle cx="10" cy="10" r="8" stroke="currentColor" strokeWidth="1.5" />
                    <path d="M10 8.5v5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                    <circle cx="10" cy="6" r="1" fill="currentColor" />
                </svg>
            </button>

            {open && typeof document !== 'undefined' && createPortal(
                <div
                    ref={tooltipRef}
                    role="tooltip"
                    id={tooltipId}
                    onMouseEnter={() => setHovered(true)}
                    onMouseLeave={(e) => {
                        const nextTarget = e.relatedTarget as Node | null;
                        if (nextTarget && anchorRef.current?.contains(nextTarget)) return;
                        setHovered(false);
                    }}
                    className="fixed z-[9999] w-[min(260px,calc(100vw-2rem))] -translate-x-1/2 rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)] p-3 text-[11px] text-[var(--foreground)] shadow-2xl ring-1 ring-white/5"
                    style={{
                        left: layout?.left ?? -9999,
                        top: layout?.top ?? -9999,
                    }}
                >
                    <div
                        aria-hidden="true"
                        className={`absolute h-3 w-3 -translate-x-1/2 rotate-45 bg-[var(--surface-elevated)] ${layout?.placement === 'top'
                            ? '-bottom-1.5 border-b border-r border-[var(--border)]'
                            : '-top-1.5 border-l border-t border-[var(--border)]'
                            }`}
                        style={{ left: layout?.arrowLeft ?? 0 }}
                    />
                    {children}
                </div>,
                document.body,
            )}
        </span>
    );
}
