import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { StepIndicator } from '../StepIndicator';

jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({
        t: (key: string, params?: { n?: number }) => key === 'stepLabel' ? `Step ${params?.n}` : key,
    }),
}));

const steps = [
    { id: 1, label: 'Upload', icon: <span>Upload icon</span> },
    { id: 2, label: 'Captions', icon: <span>Captions icon</span> },
    { id: 3, label: 'Export', icon: <span>Export icon</span> },
];

describe('StepIndicator', () => {
    it('shows a compact active, unlocked and locked workflow state', () => {
        render(<StepIndicator currentStep={2} maxStep={2} steps={steps} onStepClick={jest.fn()} />);

        expect(screen.getByTestId('workflow-stepper')).toBeInTheDocument();
        expect(screen.getByTestId('workflow-stepper')).toHaveAttribute('aria-label', 'workflowProgressLabel');
        expect(screen.getByRole('button', { name: /Step 2 Captions/ })).toHaveAttribute('aria-current', 'step');
        expect(screen.getByRole('button', { name: /Step 1 Upload/ })).toBeEnabled();
        expect(screen.getByRole('button', { name: /Step 3 Export/ })).toBeDisabled();
    });

    it('navigates only to an unlocked step', () => {
        const onStepClick = jest.fn();
        render(<StepIndicator currentStep={2} maxStep={2} steps={steps} onStepClick={onStepClick} />);

        fireEvent.click(screen.getByRole('button', { name: /Step 1 Upload/ }));
        fireEvent.click(screen.getByRole('button', { name: /Step 3 Export/ }));

        expect(onStepClick).toHaveBeenCalledTimes(1);
        expect(onStepClick).toHaveBeenCalledWith(1);
    });
});
