import React, { useEffect, useState } from 'react';

interface VideoModalProps {
    isOpen: boolean;
    onClose: () => void;
    videoUrl: string;
}

export function VideoModal({ isOpen, onClose, videoUrl }: VideoModalProps) {
    const [visible, setVisible] = useState(false);
    const [animating, setAnimating] = useState(false);

    useEffect(() => {
        if (isOpen) {
            setVisible(true);
            // Small delay to allow render before transitioning opacity
            requestAnimationFrame(() => setAnimating(true));
        } else {
            setAnimating(false);
            const timer = setTimeout(() => setVisible(false), 300); // Match transition duration
            return () => clearTimeout(timer);
        }
    }, [isOpen]);

    if (!visible) return null;

    return (
        <div
            className={`fixed inset-0 z-50 flex items-center justify-center p-4 transition-all duration-300 ease-out ${animating ? 'bg-black/90 backdrop-blur-md opacity-100' : 'bg-black/0 backdrop-blur-none opacity-0'}`}
            onClick={onClose}
        >
            <div
                className={`relative w-full max-w-5xl aspect-video rounded-2xl overflow-hidden shadow-2xl transition-all duration-300 ease-out transform ${animating ? 'scale-100 translate-y-0' : 'scale-95 translate-y-8'}`}
                onClick={(e) => e.stopPropagation()}
            >
                <button
                    onClick={onClose}
                    className="absolute top-4 right-4 z-10 p-2 rounded-full bg-black/50 text-white/80 hover:bg-black/70 hover:text-white transition-colors"
                >
                    ✕
                </button>
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
