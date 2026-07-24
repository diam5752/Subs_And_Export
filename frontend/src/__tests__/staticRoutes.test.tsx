import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import manifest from '@/app/manifest';
import OfflinePage from '@/app/offline/page';

describe('static application routes', () => {
    it('publishes installable Subframe metadata', () => {
        expect(manifest()).toEqual(expect.objectContaining({
            name: 'Subframe · Subtitle Studio',
            start_url: '/',
            display: 'standalone',
            lang: 'el',
        }));
    });

    it('offers a working recovery route while offline', () => {
        render(<OfflinePage />);

        expect(screen.getByRole('heading')).toHaveTextContent('Δεν υπάρχει σύνδεση');
        expect(screen.getByRole('link', { name: 'Δοκιμή ξανά' })).toHaveAttribute('href', '/');
    });
});
