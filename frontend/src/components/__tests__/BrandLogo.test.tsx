import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { BrandLogo } from '@/components/BrandLogo';

describe('BrandLogo', () => {
    it('renders the canonical compact-split gsubs logo by default', () => {
        // REGRESSION: Full wordmarks drifted between horizontal and stacked
        // waveform-to-arrow variants instead of the selected compact split mark.
        render(<BrandLogo className="brand-test" />);

        const logo = screen.getByRole('img', { name: 'gsubs' });
        expect(logo).toHaveAttribute('src', '/brand/gsubs-logo.svg');
        expect(logo).toHaveAttribute('width', '680');
        expect(logo).toHaveAttribute('height', '152');
        expect(logo).toHaveClass('brand-test');
    });

    it('supports the matching compact mark asset', () => {
        render(<BrandLogo markOnly />);
        expect(screen.getByRole('img', { name: 'gsubs' }))
            .toHaveAttribute('src', '/brand/gsubs-mark.svg');
        expect(screen.getByRole('img', { name: 'gsubs' }))
            .toHaveAttribute('width', '256');
        expect(screen.getByRole('img', { name: 'gsubs' }))
            .toHaveAttribute('height', '256');
    });
});
