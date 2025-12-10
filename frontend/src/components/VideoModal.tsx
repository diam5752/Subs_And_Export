import React, { useEffect, useCallback, useRef } from 'react';

interface VideoModalProps {
    isOpen: boolean;
    onClose: () => void;
    videoUrl: string;
}

export function VideoModal({ isOpen, onClose, videoUrl }: VideoModalProps) {
    const containerRef = useRef<HTMLDivElement>(null);

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
        } else {
            document.removeEventListener('keydown', handleKeyDown);
            document.body.style.overflow = '';
        }
        return () => {
            document.removeEventListener('keydown', handleKeyDown);
            document.body.style.overflow = '';
        };
    }, [isOpen, handleKeyDown]);

    // Don't render if not open and no video
    if (!isOpen || !videoUrl) return null;

    return (
        <div
            ref={containerRef}
            className="fixed inset-0 z-50 flex items-center justify-center p-4 transition-all duration-300 ease-out cursor-pointer bg-black/95 backdrop-blur-2xl"
            onClick={onClose}
        >
            {/* Cinematic vignette overlay */}
            <div
                className="vignette-overlay absolute inset-0 pointer-events-none"
            />

            {/* Click outside hint - bottom center */}
            <div className="absolute bottom-8 left-1/2 -translate-x-1/2 flex items-center gap-2 text-white/50 text-sm">
                <span className="px-3 py-1.5 rounded-full bg-white/10 backdrop-blur-sm border border-white/10">
                    Click outside or press <kbd className="px-1.5 py-0.5 mx-1 rounded bg-white/20 text-white/70 text-xs font-mono">ESC</kbd> to close
                </span>
            </div>

            {/* Video container */}
            <div
                className="video-container-glow relative w-full max-w-5xl aspect-video rounded-2xl overflow-hidden shadow-2xl cursor-default"
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
