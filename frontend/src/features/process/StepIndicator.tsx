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
    // Default maxStep to currentStep if not provided (backward compatibility)
    const effectiveMaxStep = maxStep ?? currentStep;

    return (
        <div className="w-full max-w-4xl mx-auto mb-10 px-4">
            <div className="relative flex items-center justify-between">
                {/* Connecting Line Background */}
                <div className="absolute left-0 top-1/2 -translate-y-1/2 w-full h-1 bg-[var(--surface-elevated)] rounded-full -z-10" />

                {/* Active Progress Line */}
                <div
                    className="absolute left-0 top-1/2 -translate-y-1/2 h-1 bg-gradient-to-r from-[var(--accent)] to-[var(--accent-secondary)] rounded-full -z-10 transition-all duration-700 ease-out"
                    style={{
                        // Width should reflect the maxStep, showing the full unlocked path
                        width: `${((effectiveMaxStep - 1) / (steps.length - 1)) * 100}%`
                    }}
                />

                {steps.map((step) => {
                    const isActive = currentStep === step.id; // Strictly active (currently viewing)

                    const isUnlocked = step.id <= effectiveMaxStep; // Accessible (unlocked)

                    // Determine visual state:
                    // 1. Active: Big, Glowing, Accent color
                    // 2. Unlocked (Future or Past): Accent color (like Completed), interactive
                    // 3. Locked: Muted, Gray
                    const shouldShowAccent = isActive || isUnlocked;

                    const handleKeyDown = (e: React.KeyboardEvent) => {
                        if (onStepClick && isUnlocked && (e.key === 'Enter' || e.key === ' ')) {
                            e.preventDefault();
                            onStepClick(step.id);
                        }
                    };

                    const isClickable = onStepClick && isUnlocked;

                    return (
                        <div
                            key={step.id}
                            className={`group relative flex flex-col items-center ${isClickable ? 'cursor-pointer' : 'cursor-default'}`}
                            onClick={() => isClickable && onStepClick?.(step.id)}
                            role={isClickable ? "button" : undefined}
                            tabIndex={isClickable ? 0 : undefined}
                            onKeyDown={handleKeyDown}
                        >
                            {/* Step Circle */}
                            <div
                                className={`w-12 h-12 rounded-full flex items-center justify-center border-2 transition-all duration-500 z-10 ${isActive
                                    ? 'bg-[var(--accent)] border-[var(--accent)] shadow-[0_0_20px_-5px_var(--accent)] scale-110'
                                    : shouldShowAccent
                                        ? 'bg-[var(--surface-elevated)] border-[var(--accent)] text-[var(--accent)] scale-100 hover:scale-105 hover:shadow-[0_0_15px_-5px_var(--accent)]'
                                        : 'bg-[var(--surface-elevated)] border-[var(--border)] text-[var(--muted)]'
                                    } ${isClickable && !isActive ? 'hover:scale-105 hover:border-[var(--accent)] transition-all' : ''}`}
                            >
                                <div className={`transition-all duration-500 ${isActive ? 'text-white' : shouldShowAccent ? 'text-[var(--accent)]' : 'text-[var(--muted)]'}`}>
                                    {step.icon}
                                </div>
                            </div>

                            {/* Label */}
                            <div className={`absolute top-full mt-3 text-center transition-all duration-500 w-24 ${step.id === 1 ? 'left-0' : step.id === steps.length ? 'right-0' : 'left-1/2 -translate-x-1/2'
                                } ${isActive
                                    ? 'opacity-100 transform translate-y-0'
                                    : 'opacity-50 transform -translate-y-1'
                                }`}>
                                <span className={`text-xs font-bold tracking-wider uppercase block mb-0.5 ${isActive ? 'text-[var(--accent)] scale-110' : shouldShowAccent ? 'text-[var(--accent)] opacity-80' : 'text-[var(--muted)]'}`}>
                                    {t('stepLabel', { n: step.id }) || `Step ${step.id}`}
                                </span>
                                <span className={`text-sm font-semibold ${isActive ? 'text-[var(--foreground)]' : 'text-[var(--muted)]'}`}>
                                    {step.label}
                                </span>
                            </div>
                        </div>
                    );
                })}
            </div>
            {/* Spacing for labels */}
            <div className="h-14"></div>
        </div >
    );
});
