import React from 'react';

interface PhoneFrameProps {
    children: React.ReactNode;
    className?: string;
    showNotch?: boolean;
    showStatusIcons?: boolean;
    showSocialOverlays?: boolean;
    showHomeIndicator?: boolean;
}

export const PhoneFrame: React.FC<PhoneFrameProps> = ({
    children,
    className = '',
    showNotch = true,
    showStatusIcons = true,
    showSocialOverlays = true,
    showHomeIndicator = true,
}) => {
    return (
        <div
            className={`relative isolate [transform:translateZ(0)] [backface-visibility:hidden] bg-slate-900 rounded-[40px] shadow-[0_0_0_8px_rgb(30,41,59),0_20px_50px_-12px_rgba(0,0,0,0.5)] ring-1 ring-white/5 ${className}`}
        >
            {/* The bezel is created by the shadow above. The content sits inside. */}

            {/* Inner Content - Clipped */}
            <div className="absolute inset-0 rounded-[32px] overflow-hidden bg-black flex flex-col items-center">
                {/* Notch/Dynamic Island - slightly refined shape */}
                {showNotch && (
                    <div className="absolute top-4 w-[100px] h-[28px] bg-black rounded-full z-40" />
                )}

                {/* Signal/Battery Icons */}
                {showStatusIcons && (
                    <div className="absolute top-5 right-7 flex gap-1.5 z-30 pointer-events-none mix-blend-difference text-white">
                        <div className="w-5 h-3 bg-current opacity-80 rounded-[2px]" />
                        <div className="w-0.5 h-1.5 bg-current opacity-80 rounded-[1px] self-center" />
                    </div>
                )}

                {/* Social Sidebar */}
                {showSocialOverlays && (
                    <div className="absolute bottom-24 right-4 w-9 flex flex-col gap-5 items-center z-30 pointer-events-none">
                        <div className="w-9 h-9 bg-white/20 rounded-full shadow-sm backdrop-blur-sm" />
                        <div className="w-9 h-9 bg-white/20 rounded-full shadow-sm backdrop-blur-sm" />
                        <div className="w-9 h-9 bg-white/20 rounded-full shadow-sm backdrop-blur-sm" />
                    </div>
                )}

                {/* Social Bottom Info */}
                {showSocialOverlays && (
                    <div className="absolute bottom-8 left-5 right-14 flex flex-col gap-2.5 z-30 pointer-events-none">
                        <div className="h-3 w-3/4 bg-white/20 rounded-full backdrop-blur-sm" />
                        <div className="h-3 w-1/2 bg-white/15 rounded-full backdrop-blur-sm" />
                    </div>
                )}

                {/* Home Indicator */}
                {showHomeIndicator && (
                    <div className="absolute bottom-2 w-1/3 h-1 bg-white/40 rounded-full z-30 pointer-events-none text-center" />
                )}

                {/* Main Viewport */}
                <div className="relative w-full h-full bg-black">
                    {children}
                </div>
            </div>
        </div>
    );
};
