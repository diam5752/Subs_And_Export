import React, { useMemo } from 'react';

// Types matching Backend Cue
interface WordTiming {
    start: number;
    end: number;
    text: string;
}

export interface Cue {
    start: number;
    end: number;
    text: string;
    words?: WordTiming[];
}

interface SubtitleOverlayProps {
    currentTime: number;
    cues: Cue[];
    settings: {
        position: number; // 5-95% (from bottom usually)
        color: string;
        fontSize: number; // 50-150%
        karaoke: boolean;
        maxLines: number;
        shadowStrength: number;
    };
    videoWidth?: number;
}

export const SubtitleOverlay: React.FC<SubtitleOverlayProps> = ({
    currentTime,
    cues,
    settings,
    videoWidth = 1080,
}) => {
    // 1. Find active cue
    const activeCue = useMemo(() => {
        return cues.find(c => currentTime >= c.start && currentTime < c.end);
    }, [currentTime, cues]);

    if (!activeCue) return null;

    // 2. Base Styles
    // Map settings to CSS
    const { containerStyle, textStyle, activeColor } = useMemo(() => {
        const bottomPct = settings.position; // Directly use as bottom %

        // Backend uses 62px base font size on 1080px width (approx 5.74%)
        // Backend uses 80px margins on 1080px width (approx 7.4%)
        const baseSize = videoWidth * (62 / 1080);
        const currentSize = baseSize * (settings.fontSize / 100);

        // Shadow logic (approximate ASS shadow)
        const shadowPx = settings.shadowStrength * (videoWidth / 1000);
        const textShadow = `
            ${shadowPx}px ${shadowPx}px 0px rgba(0,0,0,0.8),
            -${shadowPx}px -1px 0px rgba(0,0,0,0.8),
            1px -${shadowPx}px 0px rgba(0,0,0,0.8)
        `;

        const container = {
            position: 'absolute' as const,
            bottom: `${bottomPct}%`,
            left: '7.4%', // Match backend 80/1080 margin
            right: '7.4%',
            textAlign: 'center' as const,
            pointerEvents: 'none' as const,
            zIndex: 20,
        };

        const text = {
            fontFamily: 'Montserrat, sans-serif', // Match generic bold font
            fontWeight: 900,
            fontSize: `${currentSize}px`,
            lineHeight: 1.2,
            textShadow: textShadow,
            textTransform: 'uppercase' as const,
            color: 'white', // Default base color (usually secondary check)
            // We'll handle primary color in inner spans
            whiteSpace: 'pre-wrap' as const,
        };

        return { containerStyle: container, textStyle: text, activeColor: settings.color };
    }, [settings.position, settings.fontSize, settings.shadowStrength, settings.color, videoWidth]);

    // 3. Render Content

    // Mode A: One Word At A Time (maxLines === 0)
    if (settings.maxLines === 0 && activeCue.words && activeCue.words.length > 0) {
        const currentWord = activeCue.words.find(w => currentTime >= w.start && currentTime < w.end);

        // If between words in the same cue, maybe show nothing or the last/next? 
        // Typically strict sync = show matching. If silence, show nothing.
        if (!currentWord) return null;

        return (
            <div style={containerStyle}>
                <div style={{ ...textStyle, color: settings.color, transform: 'scale(1.1)', transition: 'all 0.1s ease-out' }}>
                    {String(currentWord.text).toUpperCase()}
                </div>
            </div>
        );
    }

    // Mode B: Karaoke / Standard Static
    // If Karaoke is OFF or NO Words, just render text in Primary Color
    if (!settings.karaoke || !activeCue.words || activeCue.words.length === 0) {
        return (
            <div style={containerStyle}>
                <div style={{ ...textStyle, color: settings.color }}>
                    {activeCue.text}
                </div>
            </div>
        );
    }

    // Mode C: Karaoke Fill (Highlight active word in sentence)
    return (
        <div style={containerStyle}>
            <div style={textStyle}>
                {activeCue.words.map((word, idx) => {
                    const isActive = currentTime >= word.start && currentTime < word.end;

                    const wordColor = isActive ? settings.color : 'rgba(255,255,255, 0.9)';
                    const wordScale = isActive ? 'scale(1.1)' : 'scale(1)';
                    const transition = 'all 0.1s ease-out';

                    return (
                        <span
                            key={`${word.start}-${idx}`}
                            style={{
                                color: wordColor,
                                display: 'inline-block',
                                transform: wordScale,
                                transition: transition,
                                margin: '0 0.2em'
                            }}
                        >
                            {String(word.text).toUpperCase()}
                        </span>
                    );
                })}
            </div>
        </div>
    );
};
