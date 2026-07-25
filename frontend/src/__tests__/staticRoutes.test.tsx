import React from 'react';
import fs from 'fs';
import path from 'path';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import manifest from '@/app/manifest';
import OfflinePage from '@/app/offline/page';

describe('static application routes', () => {
    it('publishes installable gsubs metadata', () => {
        expect(manifest()).toEqual(expect.objectContaining({
            name: 'gsubs · Subtitle Studio',
            short_name: 'gsubs',
            start_url: '/',
            display: 'standalone',
            lang: 'el',
        }));
        expect(manifest().icons).toEqual(expect.arrayContaining([
            expect.objectContaining({ src: '/icon.png', sizes: '1024x1024' }),
        ]));
    });

    it('offers a working recovery route while offline', () => {
        render(<OfflinePage />);

        expect(screen.getByText('GSUBS / OFFLINE')).toBeInTheDocument();
        expect(screen.getByRole('heading')).toHaveTextContent('Δεν υπάρχει σύνδεση');
        expect(screen.getByRole('link', { name: 'Δοκιμή ξανά' })).toHaveAttribute('href', '/');
    });

    it('ships the production logo, mark, icon and watermark assets', () => {
        const publicRoot = path.join(process.cwd(), 'public');
        const assetPaths = [
            'brand/gsubs-logo-light.svg',
            'brand/gsubs-logo-dark.svg',
            'brand/gsubs-logo-stacked-light.svg',
            'brand/gsubs-logo-stacked-dark.svg',
            'brand/gsubs-mark.svg',
            'brand/gsubs-watermark.svg',
            'gsubs-watermark.png',
            'icon.png',
        ];

        for (const assetPath of assetPaths) {
            expect(fs.statSync(path.join(publicRoot, assetPath)).size).toBeGreaterThan(0);
        }

        const lightLogo = fs.readFileSync(
            path.join(publicRoot, 'brand/gsubs-logo-light.svg'),
            'utf8',
        );
        expect(lightLogo).toContain('Audio waveform becoming subtitle lines');
        expect(lightLogo).toContain('#166095');
        expect(lightLogo).toContain('#c66a21');
    });
});
