import React, { useCallback } from 'react';
import { StepIndicator } from './StepIndicator';
import { ProcessProvider, useProcessContext, ProcessingOptions } from './ProcessContext';
import { PlaybackProvider } from './PlaybackContext';
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
const ProcessViewLayout = React.memo(({ currentStep, steps, selectedFile, isProcessing, selectedJob, setOverrideStep }: { currentStep: number; steps: any[]; selectedFile: File | null; isProcessing: boolean; selectedJob: JobResponse | null; setOverrideStep: (s: number | null) => void }) => {
    const { t } = useI18n();
    const [showEngineSettings, setShowEngineSettings] = React.useState(false);
    const showUploadSection = currentStep <= 2;
    const showPreviewSection = currentStep === 3 && selectedJob?.status === 'completed';

    const handleStepClick = React.useCallback((stepId: number) => {
        setOverrideStep(stepId);

        setTimeout(() => {
            const sectionId = stepId === 3 ? 'step-3-wrapper' : 'primary-workspace';
            const element = document.getElementById(sectionId);
            if (element) {
                const rect = element.getBoundingClientRect();
                const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
                const offset = 108;
                const targetY = rect.top + scrollTop - offset;
                window.scrollTo({ top: targetY, behavior: 'smooth' });
            }
        }, 180);
    }, [setOverrideStep]);

    const maxStep = React.useMemo(() => {
        if (selectedJob?.status === 'completed') return 3;
        if (selectedFile || selectedJob || isProcessing) return 2;
        return 1;
    }, [isProcessing, selectedFile, selectedJob]);

    return (
        <div className="studio-workflow">
            {showUploadSection && (
                <div id="primary-workspace" className="studio-primary-workspace scroll-mt-28">
                    <UploadSection />
                </div>
            )}

            {showPreviewSection && (
                <div id="step-3-wrapper" className="studio-primary-workspace scroll-mt-28">
                    <PreviewSection />
                </div>
            )}

            <StepIndicator currentStep={currentStep} steps={steps} onStepClick={handleStepClick} maxStep={maxStep} />

            <div className="studio-engine-settings">
                <div className="studio-engine-summary" data-testid="mock-mode-badge">
                    <span className="studio-engine-dot" aria-hidden="true" />
                    <span>Mock Studio</span>
                    <strong>€0</strong>
                </div>
                <button
                    type="button"
                    className="studio-engine-toggle"
                    data-testid="engine-settings-toggle"
                    aria-expanded={showEngineSettings}
                    onClick={() => setShowEngineSettings((visible) => !visible)}
                >
                    {showEngineSettings ? t('engineSettingsHide') : t('engineSettingsShow')}
                </button>
            </div>

            {showEngineSettings && (
                <div id="engine-settings-panel" className="animate-fade-in">
                    <ModelSelector />
                </div>
            )}
        </div>
    );
});
ProcessViewLayout.displayName = 'ProcessViewLayout';

export function ProcessViewContent() {
    const { t } = useI18n();
    const { currentStep, selectedFile, isProcessing, selectedJob, setOverrideStep } = useProcessContext();

    const STEPS = React.useMemo(() => [
        {
            id: 1,
            label: t('stepUpload') || 'Upload',
            icon: (
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
                </svg>
            )
        },
        {
            id: 2,
            label: t('stepCaptions') || 'Captions',
            icon: (
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
            )
        },
        {
            id: 3,
            label: t('stepExport') || 'Export',
            icon: (
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.818v6.364a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
            )
        }
    ], [t]);

    return <ProcessViewLayout currentStep={currentStep} steps={STEPS} selectedFile={selectedFile} isProcessing={isProcessing} selectedJob={selectedJob} setOverrideStep={setOverrideStep} />;
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
            <PlaybackProvider>
                <ProcessViewContent />
            </PlaybackProvider>
        </ProcessProvider>
    );
}
