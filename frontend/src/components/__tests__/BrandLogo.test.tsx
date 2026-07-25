import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { BrandLogo } from '@/components/BrandLogo';

describe('BrandLogo', () => {
    it('renders the light-surface horizontal gsubs logo by default', () => {
        render(<BrandLogo className="brand-test" />);

        const logo = screen.getByRole('img', { name: 'gsubs' });
        expect(logo).toHaveAttribute('src', '/brand/gsubs-logo-light.svg');
        expect(logo).toHaveAttribute('width', '640');
        expect(logo).toHaveClass('brand-test');
    });

    it('supports the dark-surface and compact mark assets', () => {
        const { rerender } = render(<BrandLogo surface="dark" />);
        expect(screen.getByRole('img', { name: 'gsubs' }))
            .toHaveAttribute('src', '/brand/gsubs-logo-dark.svg');

        rerender(<BrandLogo markOnly />);
        expect(screen.getByRole('img', { name: 'gsubs' }))
            .toHaveAttribute('src', '/brand/gsubs-mark.svg');
        expect(screen.getByRole('img', { name: 'gsubs' }))
            .toHaveAttribute('width', '256');
    });

    it('supports a stacked wordmark for compact header placement', () => {
        // REGRESSION: The header used the wide horizontal wordmark instead of
        // placing the gsubs name underneath the symbol.
        const { rerender } = render(<BrandLogo layout="stacked" />);
        const logo = screen.getByRole('img', { name: 'gsubs' });

        expect(logo).toHaveAttribute('src', '/brand/gsubs-logo-stacked-light.svg');
        expect(logo).toHaveAttribute('width', '280');
        expect(logo).toHaveAttribute('height', '208');

        rerender(<BrandLogo layout="stacked" surface="dark" />);
        expect(screen.getByRole('img', { name: 'gsubs' }))
            .toHaveAttribute('src', '/brand/gsubs-logo-stacked-dark.svg');
    });
});
