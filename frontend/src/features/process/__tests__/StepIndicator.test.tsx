import React from 'react';
import { render, screen } from '@testing-library/react';
import { StepIndicator } from '../StepIndicator';
import { I18nProvider } from '@/context/I18nContext';

// Mock translation function
const mockT = (key: string, params?: { n: number }) => params ? `${key} ${params.n}` : key;
jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({ t: mockT }),
    I18nProvider: ({ children }: { children: React.ReactNode }) => children,
}));

describe('StepIndicator', () => {
    const steps = [
        { id: 1, label: 'Model', icon: <span>1</span> },
        { id: 2, label: 'Upload', icon: <span>2</span> },
        { id: 3, label: 'Review', icon: <span>3</span> },
    ];

    it('should have semantic list structure', () => {
        render(
            <StepIndicator currentStep={1} steps={steps} maxStep={3} />
        );

        // <nav> containing <ol> containing <li>s
        const nav = screen.getByRole('navigation', { name: /progressSteps/ });
        expect(nav).toBeInTheDocument();

        const list = screen.getByRole('list');
        expect(list).toBeInTheDocument();

        const listItems = screen.getAllByRole('listitem');
        expect(listItems.length).toBe(3);
    });

    it('should show active state correctly', () => {
         render(
             <StepIndicator currentStep={1} steps={steps} maxStep={3} onStepClick={() => {}} />
        );

        const buttons = screen.getAllByRole('button');
        const activeStep = buttons[0];

        expect(activeStep).toHaveAttribute('aria-current', 'step');
        expect(buttons[1]).not.toHaveAttribute('aria-current');
    });
});
