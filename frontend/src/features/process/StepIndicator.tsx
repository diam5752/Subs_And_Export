import React from 'react';
import { useI18n } from '@/context/I18nContext';

interface StepIndicatorProps {
    currentStep: number; // 1, 2, or 3
    steps: {
        id: number;
        label: string;
        icon: React.ReactNode;
    }[];
    maxStep?: number; // The furthest step the user has unlocked (1, 2, or 3)
    onStepClick?: (stepId: number) => void;
}

export const StepIndicator = React.memo(function StepIndicator({ currentStep, steps, onStepClick, maxStep }: StepIndicatorProps) {
    const { t } = useI18n();
    const effectiveMaxStep = maxStep ?? currentStep;

    return (
        <div className="studio-stepper" data-testid="workflow-stepper" aria-label={t('workflowProgressLabel')}>
            <div className="studio-stepper-track">
                {steps.map((step) => {
                    const isActive = currentStep === step.id;
                    const isUnlocked = step.id <= effectiveMaxStep;
                    const isClickable = Boolean(onStepClick && isUnlocked);
                    const state = isActive ? 'active' : isUnlocked ? 'unlocked' : 'locked';

                    return (
                        <React.Fragment key={step.id}>
                            <button
                                type="button"
                                className="studio-step"
                                data-state={state}
                                aria-label={`${t('stepLabel', { n: step.id })} ${step.label}`}
                                aria-current={isActive ? 'step' : undefined}
                                disabled={!isClickable}
                                onClick={() => onStepClick?.(step.id)}
                            >
                                <span className="studio-step-number">{String(step.id).padStart(2, '0')}</span>
                                <span className="studio-step-copy">
                                    <small>{t('stepLabel', { n: step.id })}</small>
                                    <strong>{step.label}</strong>
                                </span>
                            </button>
                            {step.id !== steps.at(-1)?.id && (
                                <span
                                    className="studio-step-connector"
                                    data-state={step.id < effectiveMaxStep ? 'complete' : 'pending'}
                                    aria-hidden="true"
                                />
                            )}
                        </React.Fragment>
                    );
                })}
            </div>
        </div>
    );
});
