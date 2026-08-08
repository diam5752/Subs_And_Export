import React from 'react';
import { render } from '@testing-library/react';
import '@testing-library/jest-dom';
import { PhoneFrame } from '@/components/PhoneFrame';

describe('PhoneFrame', () => {
    it('keeps decorative phone chrome out of the video hit target', () => {
        const { container } = render(
            <PhoneFrame
                showStatusIcons={false}
                showSocialOverlays={false}
                showHomeIndicator={false}
            >
                <button type="button">Video target</button>
            </PhoneFrame>,
        );

        const notch = container.querySelector('.top-4');
        expect(notch).toHaveClass('pointer-events-none');
    });
});
