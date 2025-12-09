import React, { useEffect, useState, useCallback } from 'react';

interface VideoModalProps {
    isOpen: boolean;
    onClose: () => void;
    videoUrl: string;
}

export function VideoModal({ isOpen, onClose, videoUrl }: VideoModalProps) {
    const [visible, setVisible] = useState(false);
    const [animating, setAnimating] = useState(false);

    // Handle escape key to close modal
    const handleKeyDown = useCallback((e: KeyboardEvent) => {
        if (e.key === 'Escape') {
            onClose();
        }
    }, [onClose]);

    useEffect(() => {
        if (isOpen) {
            setVisible(true);
            requestAnimationFrame(() => setAnimating(true));
            document.addEventListener('keydown', handleKeyDown);
            // Prevent body scroll when modal is open
            document.body.style.overflow = 'hidden';
        } else {
            setAnimating(false);
            document.removeEventListener('keydown', handleKeyDown);
            document.body.style.overflow = '';
            const timer = setTimeout(() => setVisible(false), 300);
            return () => clearTimeout(timer);
        }
        return () => {
            document.removeEventListener('keydown', handleKeyDown);
            document.body.style.overflow = '';
        };
    }, [isOpen, handleKeyDown]);

    if (!visible) return null;

    return (
        <div
            className={`fixed inset-0 z-50 flex items-center justify-center p-4 transition-all duration-300 ease-out cursor-pointer ${animating
                    ? 'bg-black/95 backdrop-blur-2xl opacity-100'
                    : 'bg-black/0 backdrop-blur-none opacity-0'
                }`}
            onClick={onClose}
        >
            {/* Cinematic vignette overlay */}
            <div
                className={`absolute inset-0 pointer-events-none transition-opacity duration-500 ${animating ? 'opacity-100' : 'opacity-0'}`}
                style={{
                    background: 'radial-gradient(ellipse at center, transparent 40%, rgba(0,0,0,0.6) 100%)'
                }}
            />

            {/* Click outside hint - bottom center */}
            <div className={`absolute bottom-8 left-1/2 -translate-x-1/2 flex items-center gap-2 text-white/50 text-sm transition-all duration-500 ${animating ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}>
                <span className="px-3 py-1.5 rounded-full bg-white/10 backdrop-blur-sm border border-white/10">
                    Click outside or press <kbd className="px-1.5 py-0.5 mx-1 rounded bg-white/20 text-white/70 text-xs font-mono">ESC</kbd> to close
                </span>
            </div>

            {/* Video container */}
            <div
                className={`relative w-full max-w-5xl aspect-video rounded-2xl overflow-hidden shadow-2xl transition-all duration-300 ease-out transform cursor-default ${animating ? 'scale-100 translate-y-0' : 'scale-95 translate-y-8'
                    }`}
                style={{
                    boxShadow: animating ? '0 0 100px 20px rgba(0,0,0,0.8), 0 0 60px 10px var(--accent)' : 'none'
                }}
                onClick={(e) => e.stopPropagation()}
            >
                {/* Close button */}
                <button
                    onClick={onClose}
                    className="absolute top-4 right-4 z-10 p-3 rounded-full bg-black/60 text-white/80 hover:bg-black/80 hover:text-white transition-all hover:scale-110"
                    aria-label="Close video"
                >
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                </button>

                {/* Video player */}
                <video
                    src={videoUrl}
                    className="w-full h-full object-contain bg-black"
                    controls
                    autoPlay
                />
            </div>
        </div>
    );
}

