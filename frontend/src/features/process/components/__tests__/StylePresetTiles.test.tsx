import React from 'react';
import { render, screen } from '@testing-library/react';
import { StylePresetTiles, StylePreset } from '../StylePresetTiles';
import { I18nProvider } from '@/context/I18nContext';

// Mock dependencies
const mockPresets: StylePreset[] = [
    {
        id: 'tiktok',
        name: 'TikTok Pro',
        description: 'Viral, attention-grabbing style',
        emoji: '🎵',
        colorClass: 'from-yellow-500 to-orange-500',
        settings: { position: 16, lines: 1, size: 100, color: '#FFFF00', karaoke: true }
    },
    {
        id: 'cinema',
        name: 'Cinema',
        description: 'Classic movie subtitles',
        emoji: '🎬',
        colorClass: 'from-gray-500 to-black',
        settings: { position: 10, lines: 2, size: 80, color: '#FFFFFF', karaoke: false }
    }
];

describe('StylePresetTiles', () => {
    it('renders with accessible labels and descriptions', () => {
        const handleSelect = jest.fn();
        const handleLastUsed = jest.fn();

        render(
            <I18nProvider initialLocale="en">
                <StylePresetTiles
                    presets={mockPresets}
                    activePreset={null}
                    lastUsedSettings={null}
                    onSelectPreset={handleSelect}
                    onSelectLastUsed={handleLastUsed}
                />
            </I18nProvider>
        );

        // Check if buttons exist with role="radio"
        const buttons = screen.getAllByRole('radio');
        expect(buttons.length).toBe(3); // 2 presets + 1 last used

        // Get the first preset button
        const tiktokBtn = buttons[0];

        // It should refer to its name and description via ID
        const labelledBy = tiktokBtn.getAttribute('aria-labelledby');
        const describedBy = tiktokBtn.getAttribute('aria-describedby');

        expect(labelledBy).toBeTruthy();
        expect(describedBy).toBeTruthy();

        // Verify the elements exist
        const nameEl = document.getElementById(labelledBy as string);
        const descEl = document.getElementById(describedBy as string);

        expect(nameEl).toHaveTextContent('TikTok Pro');
        expect(descEl).toHaveTextContent('Viral, attention-grabbing style');
    });

    it('correctly labels the Last Used button', () => {
        const handleSelect = jest.fn();
        const handleLastUsed = jest.fn();

        render(
            <I18nProvider initialLocale="en">
                <StylePresetTiles
                    presets={mockPresets}
                    activePreset={null}
                    lastUsedSettings={null}
                    onSelectPreset={handleSelect}
                    onSelectLastUsed={handleLastUsed}
                />
            </I18nProvider>
        );

        const lastUsedBtn = screen.getAllByRole('radio')[2];

        const labelledBy = lastUsedBtn.getAttribute('aria-labelledby');
        const describedBy = lastUsedBtn.getAttribute('aria-describedby');

        expect(labelledBy).toBeTruthy();
        expect(describedBy).toBeTruthy();

        expect(document.getElementById(labelledBy as string)).toHaveTextContent('Last Used');
        expect(document.getElementById(describedBy as string)).toHaveTextContent(/No previous exports yet/i);
    });
});
