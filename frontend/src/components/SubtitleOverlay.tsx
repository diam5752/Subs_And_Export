import React, { useMemo, memo } from 'react';
import { TranscriptionCue } from '../lib/api';
import { findCueIndexAtTime } from '../lib/subtitleUtils';

export type Cue = TranscriptionCue;

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

export const SubtitleOverlay = memo<SubtitleOverlayProps>(({
    currentTime,
    cues,
    settings,
    videoWidth = 1080,
}) => {
    // 1. Find active cue (Optimized with hint for linear playback)
    const hintIndexRef = React.useRef(-1);

    // We calculate the index during render to ensure the UI is always consistent with currentTime
    // but we use the previous hint to make this calculation O(1) in most cases.
    const activeCueIndex = useMemo(() => {
        return findCueIndexAtTime(cues, currentTime, hintIndexRef.current);
    }, [currentTime, cues]);

    // Update the hint for the NEXT frame after rendering is committed.
    // This avoids side-effects during the render phase (React Strict Mode safety).
    React.useEffect(() => {
        if (activeCueIndex !== -1) {
            hintIndexRef.current = activeCueIndex;
        }
    }, [activeCueIndex]);

    const activeCue = activeCueIndex !== -1 ? cues[activeCueIndex] : undefined;

    // 2. Base Styles
    // Map settings to CSS
    const { containerStyle, textStyle } = useMemo(() => {
        const bottomPct = settings.position; // Directly use as bottom %

        // Backend uses 62px base font size on 1080px width (approx 5.74%)
        // Backend uses 80px margins on 1080px width (approx 7.4%)
        const baseSize = videoWidth * (62 / 1080);
        const currentSize = baseSize * (settings.fontSize / 100);

        // Shadow logic (approximate ASS shadow)
        const shadowPx = settings.shadowStrength * (videoWidth / 1000);

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
            fontFamily: "'Arial Black', 'Montserrat', sans-serif", // Match backend default
            fontWeight: 900,
            fontSize: `${currentSize}px`,
            lineHeight: 1.2,
            WebkitTextStroke: `${shadowPx}px rgba(0,0,0,0.8)`,
            paintOrder: 'stroke fill',
            textShadow: `${shadowPx}px ${shadowPx}px 0px rgba(0,0,0,0.8)`, // Drop shadow to match backend
            textTransform: 'uppercase' as const,
            color: 'white', // Default base color (usually secondary check)
            whiteSpace: 'pre-wrap' as const,
        };

        return { containerStyle: container, textStyle: text };
    }, [settings.position, settings.fontSize, settings.shadowStrength, videoWidth]);

    // OPTIMIZATION: Calculate active word index separately
    // This allows us to memoize the rendered nodes and avoid re-creating them every frame
    // unless the active word actually changes.
    const activeWordIndex = useMemo(() => {
        if (!activeCue?.words) return -1;
        return activeCue.words.findIndex(w => currentTime >= w.start && currentTime < w.end);
    }, [activeCue, currentTime]);

    // 3. Render Content (Memoized)
    return useMemo(() => {
        if (!activeCue) return null;

        // Mode A: One Word At A Time (maxLines === 0)
        if (settings.maxLines === 0 && activeCue.words && activeCue.words.length > 0) {
            const currentWord = activeWordIndex !== -1 ? activeCue.words[activeWordIndex] : null;

            // If between words in the same cue, maybe show nothing or the last/next?
            // Typically strict sync = show matching. If silence, show nothing.
            if (!currentWord) return null;

            return (
                <div style={containerStyle}>
                    <div style={{ ...textStyle, color: settings.color, transform: 'scale(1.1)', transition: 'all 0.1s ease-out' }}>
                        {String(currentWord.text).trim().toUpperCase()}
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
        const karaokeNodes: React.ReactNode[] = [];
        for (const [idx, word] of activeCue.words.entries()) {
            const trimmedText = String(word.text).trim();
            if (!trimmedText) continue;

            // Use memoized activeWordIndex instead of currentTime range check
            const isActive = idx === activeWordIndex;

            const wordColor = isActive ? settings.color : 'rgba(255,255,255, 0.9)';
            const wordScale = isActive ? 'scale(1.1)' : 'scale(1)';
            const transition = 'all 0.1s ease-out';

            karaokeNodes.push(
                <span
                    key={`${word.start}-${idx}`}
                    style={{
                        color: wordColor,
                        display: 'inline-block',
                        transform: wordScale,
                        transition,
                    }}
                >
                    {trimmedText.toUpperCase()}
                </span>
            );

            if (idx < activeCue.words.length - 1) {
                karaokeNodes.push(' ');
            }
        }

        return (
            <div style={containerStyle}>
                <div style={textStyle}>
                    {karaokeNodes}
                </div>
            </div>
        );
    }, [
        activeCue,
        activeWordIndex,
        settings.maxLines,
        settings.karaoke,
        settings.color,
        containerStyle,
        textStyle
    ]);
});

SubtitleOverlay.displayName = 'SubtitleOverlay';
