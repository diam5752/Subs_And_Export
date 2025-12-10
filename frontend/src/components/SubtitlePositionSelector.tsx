import React from 'react';

interface SubtitlePositionSelectorProps {
    value: string;
    onChange: (value: string) => void;
}

export function SubtitlePositionSelector({ value, onChange }: SubtitlePositionSelectorProps) {
    // Map position to CSS 'bottom' percentage for the preview
    // These are visual approximations to match the backend logic
    // Default (MarginV 320 on 1920 height) ~= 16%
    // Top (MarginV 850) ~= 44%
    // Bottom (MarginV 120) ~= 6%
    const getPreviewBottom = (pos: string) => {
        switch (pos) {
            case 'top': return '44%';
            case 'bottom': return '6%';
            default: return '16%';
        }
    };

    const options = [
        { id: 'default', label: 'Social Default', desc: 'Optimized for Reels/TikTok UI' },
        { id: 'top', label: 'Middle / Upper', desc: 'Higher up for better visibility' },
        { id: 'bottom', label: 'Movie Style', desc: 'Cinematic low placement' },
    ];

    return (
        <div className="space-y-3">
            <label className="block text-sm font-medium text-[var(--muted)]">
                Subtitle Position
            </label>
            <div className="flex flex-col sm:flex-row gap-4">
                {/* Selection Buttons */}
                <div className="flex-1 grid grid-cols-1 gap-3">
                    {options.map((opt) => (
                        <button
                            key={opt.id}
                            onClick={(e) => {
                                e.stopPropagation();
                                onChange(opt.id);
                            }}
                            className={`p-3 rounded-lg border text-left transition-all ${value === opt.id
                                    ? 'border-[var(--accent)] bg-[var(--accent)]/10 ring-1 ring-[var(--accent)]'
                                    : 'border-[var(--border)] hover:border-[var(--accent)]/50 hover:bg-[var(--surface-elevated)]'
                                }`}
                        >
                            <div className="font-semibold text-sm">{opt.label}</div>
                            <div className="text-xs text-[var(--muted)]">{opt.desc}</div>
                        </button>
                    ))}
                </div>

                {/* Visual Preview */}
                <div className="flex-shrink-0 flex justify-center bg-[var(--surface-elevated)] p-4 rounded-xl border border-[var(--border)]">
                    <div className="relative w-[54px] h-[96px] bg-slate-800 rounded-lg border border-slate-600 overflow-hidden shadow-inner">
                        {/* Phone UI placeholders */}
                        {/* Status bar */}
                        <div className="absolute top-1 left-0 right-0 h-0.5 bg-slate-600/50 mx-2 rounded-full" />

                        {/* Social Sidebar (Like/Comment) */}
                        <div className="absolute bottom-8 right-1 w-2 flex flex-col gap-1 items-center">
                            <div className="w-1.5 h-1.5 bg-slate-600/50 rounded-full" />
                            <div className="w-1.5 h-1.5 bg-slate-600/50 rounded-full" />
                            <div className="w-1.5 h-1.5 bg-slate-600/50 rounded-full" />
                        </div>

                        {/* Social Bottom Info */}
                        <div className="absolute bottom-2 left-2 right-6 h-3 flex flex-col gap-1">
                            <div className="h-1 w-2/3 bg-slate-600/40 rounded-full" />
                            <div className="h-1 w-1/2 bg-slate-600/40 rounded-full" />
                        </div>

                        {/* Subtitle Bar - Animated */}
                        <div
                            className="absolute left-1 right-1 h-3 bg-[var(--accent)] rounded-sm shadow-[0_0_4px_rgba(0,0,0,0.5)] transition-all duration-300 ease-out flex items-center justify-center scale-90"
                            style={{ bottom: getPreviewBottom(value) }}
                        >
                            <div className="w-3/4 h-0.5 bg-white/90 rounded-full" />
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
