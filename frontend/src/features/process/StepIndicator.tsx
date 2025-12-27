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
        <div className="w-full max-w-4xl mx-auto mb-6 px-8 sm:px-12">
            <div className="relative flex items-center justify-between">
                {/* Connecting Line Background - spans between circle centers */}
                <div
                    className="absolute h-[1px] bg-[var(--border)] w-full top-6 pointer-events-none"
                    style={{
                        left: '0',
                        right: '0',
                    }}
                />

                {/* Active Progress Line */}
                <div
                    className="absolute h-[2px] bg-gradient-to-r from-[var(--accent)] via-[var(--accent-secondary)] to-[var(--accent)] rounded-full transition-all duration-700 ease-out pointer-events-none shadow-[0_0_10px_var(--accent)]"
                    style={{
                        top: '23px', // Center alignment
                        left: '24px', // Start from center of first circle
                        // Width spans from center of circle 1 to center of circle N based on maxStep
                        width: effectiveMaxStep <= 1 ? '0' : `calc(${((effectiveMaxStep - 1) / (steps.length - 1)) * 100}% - 48px)`
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
                            aria-current={isActive ? 'step' : undefined}
                            tabIndex={isClickable ? 0 : undefined}
                            onKeyDown={handleKeyDown}
                        >
                            {/* Step Circle */}
                            <div
                                className={`relative w-12 h-12 rounded-full flex items-center justify-center border-2 transition-all duration-500 z-10 ${isActive
                                    ? 'bg-[var(--surface-elevated)] border-[var(--accent)] shadow-[0_0_30px_-5px_var(--accent)] scale-110 text-[var(--accent)]'
                                    : shouldShowAccent
                                        ? 'bg-[var(--surface-elevated)] border-[var(--accent)] text-[var(--accent)] scale-100 hover:scale-105 hover:shadow-[0_0_15px_-5px_var(--accent)] hover:border-[var(--accent-secondary)]'
                                        : 'bg-[var(--surface)] border-[var(--border)] text-[var(--muted)] opacity-60'
                                    } ${isClickable && !isActive ? 'hover:scale-105 transition-all cursor-pointer' : ''}`}
                            >
                                <div className={`transition-all duration-500 ${isActive ? 'drop-shadow-[0_0_8px_rgba(249,115,22,0.5)]' : ''}`}>
                                    {step.icon}
                                </div>
                            </div>

                            {/* Label */}
                            <div className={`absolute top-full mt-3 text-center transition-all duration-500 w-40 left-1/2 -translate-x-1/2 ${isActive
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
