
import React from 'react';

interface StepIndicatorProps {
    currentStep: number; // 1, 2, or 3
    steps: {
        id: number;
        label: string;
        icon: React.ReactNode;
    }[];
    onStepClick?: (stepId: number) => void;
}

export const StepIndicator = React.memo(function StepIndicator({ currentStep, steps, onStepClick }: StepIndicatorProps) {

    return (
        <div className="w-full max-w-4xl mx-auto mb-10 px-4">
            <div className="relative flex items-center justify-between">
                {/* Connecting Line Background */}
                <div className="absolute left-0 top-1/2 -translate-y-1/2 w-full h-1 bg-[var(--surface-elevated)] rounded-full -z-10" />

                {/* Active Progress Line */}
                <div
                    className="absolute left-0 top-1/2 -translate-y-1/2 h-1 bg-gradient-to-r from-[var(--accent)] to-[var(--accent-secondary)] rounded-full -z-10 transition-all duration-700 ease-out"
                    style={{
                        width: `${((currentStep - 1) / (steps.length - 1)) * 100}%`
                    }}
                />

                {steps.map((step) => {
                    const isActive = currentStep === step.id; // Strictly active
                    const isCompleted = currentStep > step.id; // Strictly completed
                    const isFuture = currentStep < step.id;

                    const handleKeyDown = (e: React.KeyboardEvent) => {
                        if (onStepClick && (e.key === 'Enter' || e.key === ' ')) {
                            e.preventDefault();
                            onStepClick(step.id);
                        }
                    };

                    return (
                        <div
                            key={step.id}
                            className={`group relative flex flex-col items-center ${onStepClick ? 'cursor-pointer' : ''}`}
                            onClick={() => onStepClick?.(step.id)}
                            role={onStepClick ? "button" : undefined}
                            tabIndex={onStepClick ? 0 : undefined}
                            onKeyDown={handleKeyDown}
                        >
                            {/* Step Circle */}
                            <div
                                className={`w-12 h-12 rounded-full flex items-center justify-center border-2 transition-all duration-500 z-10 ${isActive
                                    ? 'bg-[var(--surface-elevated)] border-[var(--accent)] shadow-[0_0_20px_-5px_var(--accent)] scale-110'
                                    : isCompleted
                                        ? 'bg-[var(--surface-elevated)] border-[var(--accent)] text-[var(--accent)] scale-100'
                                        : 'bg-[var(--surface-elevated)] border-[var(--border)] text-[var(--muted)]'
                                    } ${onStepClick && !isActive ? 'hover:scale-105 hover:border-[var(--accent)] transition-all' : ''}`}
                            >
                                <div className={`transition-all duration-500 ${isActive || isCompleted ? 'text-[var(--accent)]' : 'text-[var(--muted)]'}`}>
                                    {step.icon}
                                </div>
                            </div>

                            {/* Label */}
                            <div className={`absolute top-full mt-3 text-center transition-all duration-500 whitespace-nowrap ${isActive
                                ? 'opacity-100 transform translate-y-0'
                                : 'opacity-50 transform -translate-y-1'
                                }`}>
                                <span className={`text-xs font-bold tracking-wider uppercase block mb-0.5 ${isActive ? 'text-[var(--accent)] scale-110' : isCompleted ? 'text-[var(--accent)] opacity-80' : 'text-[var(--muted)]'}`}>
                                    Step {step.id}
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
