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
});
