import React, { useCallback } from "react";
import dynamic from "next/dynamic";
import { StepIndicator } from "./StepIndicator";
import {
  ProcessProvider,
  useProcessContext,
  ProcessingOptions,
} from "./ProcessContext";
import { PlaybackProvider } from "./PlaybackContext";
export type { ProcessingOptions } from "./ProcessContext";
import { JobResponse } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";

// Editing, playback and export are only needed once a completed job opens.
const PreviewSection = dynamic(
  () =>
    import("./components/PreviewSection").then(
      (module) => module.PreviewSection,
    ),
  {
    loading: () => (
      <div
        data-testid="editor-workspace-loading"
        className="min-h-[calc(100dvh-10rem)] animate-pulse rounded-2xl border border-[var(--border)] bg-[var(--surface-elevated)]"
        aria-hidden="true"
      />
    ),
  },
);

// The upload controls are not rendered when a completed job opens directly.
// Keep their media-inspection and pricing code out of that low-end editor path.
const UploadSection = dynamic(
  () =>
    import("./components/UploadSection").then((module) => module.UploadSection),
  {
    loading: () => (
      <div
        data-testid="upload-workspace-loading"
        className="min-h-64 animate-pulse rounded-2xl border border-[var(--border)] bg-[var(--surface-elevated)]"
        aria-hidden="true"
      />
    ),
  },
);

interface ProcessViewProps {
  selectedFile: File | null;
  onFileSelect: (file: File | null) => void;
  isProcessing: boolean;
  progress: number;
  statusMessage: string;
  error: string;
  onStartProcessing: (options: ProcessingOptions) => Promise<void>;
  onReprocessJob: (
    sourceJobId: string,
    options: ProcessingOptions,
  ) => Promise<void>;
  onReset: () => void;
  onCancelProcessing?: () => void;
  selectedJob: JobResponse | null;
  onJobSelect: (job: JobResponse | null) => void;
  onRefreshJobs?: () => Promise<void>;
  statusStyles: Record<string, string>;
  buildStaticUrl: (path?: string | null) => string | null;
  totalJobs: number;
}

interface ProcessViewLayoutProps {
  currentStep: number;
  steps: React.ComponentProps<typeof StepIndicator>["steps"];
  selectedFile: File | null;
  isProcessing: boolean;
  selectedJob: JobResponse | null;
  setOverrideStep: (step: number | null) => void;
}

const ProcessViewLayout = React.memo(
  ({
    currentStep,
    steps,
    selectedFile,
    isProcessing,
    selectedJob,
    setOverrideStep,
  }: ProcessViewLayoutProps) => {
    const showUploadSection = currentStep <= 2;
    const showPreviewSection =
      currentStep === 3 && selectedJob?.status === "completed";

    const handleStepClick = React.useCallback(
      (stepId: number) => {
        setOverrideStep(stepId);

        setTimeout(() => {
          const sectionId =
            stepId === 3 ? "step-3-wrapper" : "primary-workspace";
          const element = document.getElementById(sectionId);
          if (element) {
            const rect = element.getBoundingClientRect();
            const scrollTop =
              window.pageYOffset || document.documentElement.scrollTop;
            const offset = 108;
            const targetY = rect.top + scrollTop - offset;
            window.scrollTo({ top: targetY, behavior: "smooth" });
          }
        }, 180);
      },
      [setOverrideStep],
    );

    const maxStep = React.useMemo(() => {
      if (selectedJob?.status === "completed") return 3;
      if (selectedFile || selectedJob || isProcessing) return 2;
      return 1;
    }, [isProcessing, selectedFile, selectedJob]);

    return (
      <div className="studio-workflow">
        <StepIndicator
          currentStep={currentStep}
          steps={steps}
          onStepClick={handleStepClick}
          maxStep={maxStep}
        />

        {showUploadSection && (
          <div
            id="primary-workspace"
            className="studio-primary-workspace scroll-mt-28"
          >
            <UploadSection />
          </div>
        )}

        {showPreviewSection && (
          <div
            id="step-3-wrapper"
            className="studio-primary-workspace scroll-mt-28"
          >
            <PreviewSection />
          </div>
        )}
      </div>
    );
  },
);
ProcessViewLayout.displayName = "ProcessViewLayout";

export function ProcessViewContent() {
  const { t } = useI18n();
  const {
    currentStep,
    selectedFile,
    isProcessing,
    selectedJob,
    setOverrideStep,
  } = useProcessContext();

  const STEPS = React.useMemo(
    () => [
      {
        id: 1,
        label: t("stepUpload") || "Upload",
      },
      {
        id: 2,
        label: t("stepCaptions") || "Captions",
      },
      {
        id: 3,
        label: t("stepExport") || "Export",
      },
    ],
    [t],
  );

  return (
    <ProcessViewLayout
      currentStep={currentStep}
      steps={STEPS}
      selectedFile={selectedFile}
      isProcessing={isProcessing}
      selectedJob={selectedJob}
      setOverrideStep={setOverrideStep}
    />
  );
}

export function ProcessView(props: ProcessViewProps) {
  const { onFileSelect, onJobSelect } = props;
  const onFileSelectInternal = useCallback(
    (file: File | null) => {
      onFileSelect(file);
      if (file) {
        onJobSelect?.(null);
      }
    },
    [onFileSelect, onJobSelect],
  );

  return (
    <ProcessProvider {...props} onFileSelect={onFileSelectInternal}>
      <PlaybackProvider>
        <ProcessViewContent />
      </PlaybackProvider>
    </ProcessProvider>
  );
}
