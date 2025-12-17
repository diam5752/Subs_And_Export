import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import { InfoTooltip } from '@/components/InfoTooltip';

describe('InfoTooltip', () => {
    it('shows tooltip on focus and hides on blur', () => {
        render(
            <InfoTooltip ariaLabel="Info: Example">
                <div>Helpful text</div>
            </InfoTooltip>
        );

        const button = screen.getByRole('button', { name: 'Info: Example' });
        expect(button).toBeInTheDocument();
        expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();

        fireEvent.focus(button);
        expect(screen.getByRole('tooltip')).toHaveTextContent('Helpful text');

        fireEvent.blur(button);
        expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    });
});

