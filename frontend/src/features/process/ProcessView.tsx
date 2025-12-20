import React, { useCallback } from 'react';
import { StepIndicator } from './StepIndicator';
import { ProcessProvider, useProcessContext, ProcessingOptions } from './ProcessContext';
export type { ProcessingOptions } from './ProcessContext';
import { ModelSelector } from './components/ModelSelector';
import { UploadSection } from './components/UploadSection';
import { PreviewSection } from './components/PreviewSection';
import { JobResponse } from '@/lib/api';
import { useI18n } from '@/context/I18nContext';

interface ProcessViewProps {
    selectedFile: File | null;
    onFileSelect: (file: File | null) => void;
    isProcessing: boolean;
    progress: number;
    statusMessage: string;
    error: string;
    onStartProcessing: (options: ProcessingOptions) => Promise<void>;
    onReprocessJob: (sourceJobId: string, options: ProcessingOptions) => Promise<void>;
    onReset: () => void;
    onCancelProcessing?: () => void;
    selectedJob: JobResponse | null;
    onJobSelect: (job: JobResponse | null) => void;
    statusStyles: Record<string, string>;
    buildStaticUrl: (path?: string | null) => string | null;
    totalJobs: number;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const ProcessViewLayout = React.memo(({ currentStep, steps, hasChosenModel, selectedJob, setOverrideStep }: { currentStep: number; steps: any[]; activeSidebarTab: string; hasVideos: boolean; hasChosenModel: boolean; isProcessing: boolean; selectedJob: JobResponse | null; setOverrideStep: (s: number | null) => void }) => {
    // Step 2: Show if model chosen OR if we are already on Step 2+ (e.g. session restored)
    const showUploadSection = hasChosenModel || currentStep >= 2;

    // Step 3: Only show when job is completed (Step 2 done)
    const showPreviewSection = selectedJob?.status === 'completed';

    const handleStepClick = React.useCallback((stepId: number) => {
        setOverrideStep(stepId);

        // Wait for CSS transitions (300ms) to complete before scrolling.
        // This ensures the target position is calculated after Step 1 has finished collapsing.
        setTimeout(() => {
            const sectionId = stepId === 1 ? 'step-1-wrapper' : stepId === 2 ? 'step-2-wrapper' : 'step-3-wrapper';
            const element = document.getElementById(sectionId);
            if (element) {
                element.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        }, 350);
    }, [setOverrideStep]);

    // Calculate maxStep (furthest unlocked step)
    const maxStep = React.useMemo(() => {
        if (selectedJob?.status === 'completed') return 3;
        if (hasChosenModel) return 2;
        return 1;
    }, [selectedJob, hasChosenModel]);

    return (
        <div className="space-y-6">
            {/* Always show all 3 steps - they appear greyed out when inactive */}
            <StepIndicator currentStep={currentStep} steps={steps} onStepClick={handleStepClick} maxStep={maxStep} />

            <div id="step-1-wrapper" className="scroll-mt-32">
                <ModelSelector />
            </div>

            {showUploadSection && (
                <div id="step-2-wrapper" className="scroll-mt-32">
                    <UploadSection />
                </div>
            )}

            {showPreviewSection && (
                <div id="step-3-wrapper" className="scroll-mt-32">
                    <PreviewSection />
                </div>
            )}
        </div>
    );
});
ProcessViewLayout.displayName = 'ProcessViewLayout';

export function ProcessViewContent() {
    const { t } = useI18n();
    const { currentStep, activeSidebarTab, hasVideos, hasChosenModel, isProcessing, selectedJob, setOverrideStep } = useProcessContext();

    const STEPS = React.useMemo(() => [
        {
            id: 1,
            label: t('modelSelectTitle') || 'Pick Model',
            icon: (
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
                </svg>
            )
        },
        {
            id: 2,
            label: t('stepUpload') || 'Upload',
            icon: (
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
            )
        },
        {
            id: 3,
            label: t('stepPreview') || 'Preview',
            icon: (
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.818v6.364a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
            )
        }
    ], [t]);

    return <ProcessViewLayout currentStep={currentStep} steps={STEPS} activeSidebarTab={activeSidebarTab} hasVideos={hasVideos} hasChosenModel={hasChosenModel} isProcessing={isProcessing} selectedJob={selectedJob} setOverrideStep={setOverrideStep} />;
}

export function ProcessView(props: ProcessViewProps) {
    const { onFileSelect, onJobSelect } = props;
    const onFileSelectInternal = useCallback((file: File | null) => {
        onFileSelect(file);
        if (file) {
            onJobSelect?.(null);
        }
    }, [onFileSelect, onJobSelect]);

    return (
        <ProcessProvider {...props} onFileSelect={onFileSelectInternal}>
            <ProcessViewContent />
        </ProcessProvider>
    );
}
