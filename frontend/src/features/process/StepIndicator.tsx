
import React from 'react';
import { useI18n } from '@/context/I18nContext';

interface StepIndicatorProps {
    currentStep: number; // 1, 2, or 3
    steps: {
        id: number;
        label: string;
        icon: React.ReactNode;
    }[];
}

export function StepIndicator({ currentStep, steps }: StepIndicatorProps) {
    const { t } = useI18n();

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

                {steps.map((step, index) => {
                    const isActive = currentStep >= step.id;
                    const isCompleted = currentStep > step.id;
                    const isLast = index === steps.length - 1;

                    return (
                        <div key={step.id} className="group relative flex flex-col items-center">
                            {/* Step Circle */}
                            <div
                                className={`w-12 h-12 rounded-full flex items-center justify-center border-2 transition-all duration-500 z-10 ${isActive
                                        ? 'bg-[var(--surface)] border-[var(--accent)] shadow-[0_0_20px_-5px_var(--accent)] scale-110'
                                        : 'bg-[var(--surface)] border-[var(--border)] text-[var(--muted)] grayscale'
                                    }`}
                            >
                                <div className={`transition-all duration-500 ${isActive ? 'text-[var(--accent)]' : 'opacity-50'}`}>
                                    {isCompleted ? (
                                        <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                                        </svg>
                                    ) : (
                                        step.icon
                                    )}
                                </div>
                            </div>

                            {/* Label */}
                            <div className={`absolute top-full mt-3 text-center transition-all duration-500 whitespace-nowrap ${isActive
                                    ? 'opacity-100 transform translate-y-0'
                                    : 'opacity-50 transform -translate-y-1'
                                }`}>
                                <span className={`text-xs font-bold tracking-wider uppercase block mb-0.5 ${isActive ? 'text-[var(--accent)]' : 'text-[var(--muted)]'}`}>
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
        </div>
    );
}
