import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { SubtitleOverlay } from '@/components/SubtitleOverlay';

describe('SubtitleOverlay', () => {
    it('renders karaoke words with spaces (no margin-based spacing)', () => {
        // REGRESSION: spacing via per-word margins reduced effective line capacity and caused
        // extra wrapped lines (e.g., selecting 1 line but seeing 2 in preview).
        render(
            <SubtitleOverlay
                currentTime={0.5}
                cues={[
                    {
                        start: 0,
                        end: 2,
                        text: ' hello world',
                        words: [
                            { start: 0, end: 1, text: ' hello' },
                            { start: 1, end: 2, text: ' world' },
                        ],
                    },
                ]}
                settings={{
                    position: 20,
                    color: '#FFFF00',
                    fontSize: 100,
                    karaoke: true,
                    maxLines: 2,
                    shadowStrength: 4,
                }}
                videoWidth={1080}
            />
        );

        expect(screen.getByText('HELLO')).toBeInTheDocument();
        expect(screen.getByText('WORLD')).toBeInTheDocument();
        const textContainer = screen.getByText('HELLO').parentElement;
        expect(textContainer).not.toBeNull();
        expect(textContainer?.textContent).toBe('HELLO WORLD');

        const wordSpan = screen.getByText('HELLO');
        expect(wordSpan.getAttribute('style')).not.toContain('margin');
    });
});
