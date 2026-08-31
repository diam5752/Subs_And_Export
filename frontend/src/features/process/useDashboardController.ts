import { useCallback, useMemo, useRef, useState } from "react";
import type { MouseEvent } from "react";
import { useAuth } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import { usePoints } from "@/context/PointsContext";
import { useDashboardAccount } from "@/features/account/useDashboardAccount";
import { useCheckoutReturnReconciliation } from "@/features/billing/useCheckoutReturnReconciliation";
import type { ProcessingOptions } from "@/features/process/ProcessView";
import {
  ELEVENLABS_MISSING_WORD_TIMESTAMPS,
  processingQuoteChangeFromError,
  processingSettings,
  reportProcessingFailure,
  uploadFailureMessage,
  type PendingProcessingAction,
} from "@/features/process/dashboardProcessing";
import { useSessionJobRestore } from "@/features/process/useSessionJobRestore";
import { useJobPolling, type JobPollingCallbacks } from "@/hooks/useJobPolling";
import { useJobs } from "@/hooks/useJobs";
import { api, type JobResponse } from "@/lib/api";
import { reportProductAction } from "@/lib/observability";
import { paidCreditLegalPublicationIsApproved } from "@/lib/paidCreditLegal";
import {
  isProcessingCreditTier,
  processVideoCostForSelection,
  transcribeProviderRequiresPaidCredits,
  type ProcessingCreditTier,
} from "@/lib/points";
import type { ProcessingGateStage } from "@/components/ProcessingGateModal";

function useDashboardFoundation() {
  const auth = useAuth();
  const points = usePoints();
  const jobs = useJobs();
  const { t } = useI18n();
  const paidCreditSalesUiApproved = paidCreditLegalPublicationIsApproved();
  const checkout = useCheckoutReturnReconciliation({
    userId: auth.user?.id ?? null,
    setWallet: points.setWallet,
    t,
  });
  const account = useDashboardAccount({
    user: auth.user,
    logout: auth.logout,
    refreshUser: auth.refreshUser,
    t,
  });
  return {
    auth,
    points,
    jobs,
    t,
    paidCreditSalesUiApproved,
    checkout,
    account,
  };
}

function useCoreProcessingState() {
  const activeUploadAbortRef = useRef<AbortController | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState("");
  const [processError, setProcessError] = useState("");
  const [canCancelProcessing, setCanCancelProcessing] = useState(false);
  const setActiveUpload = useCallback((controller: AbortController) => {
    activeUploadAbortRef.current = controller;
  }, []);
  const clearActiveUpload = useCallback((controller: AbortController) => {
    if (activeUploadAbortRef.current === controller) {
      activeUploadAbortRef.current = null;
    }
  }, []);
  const takeActiveUpload = useCallback(() => {
    const controller = activeUploadAbortRef.current;
    activeUploadAbortRef.current = null;
    return controller;
  }, []);
  const abortActiveUpload = useCallback(() => {
    activeUploadAbortRef.current?.abort();
    activeUploadAbortRef.current = null;
  }, []);
  return {
    setActiveUpload,
    clearActiveUpload,
    takeActiveUpload,
    abortActiveUpload,
    selectedFile,
    setSelectedFile,
    isProcessing,
    setIsProcessing,
    jobId,
    setJobId,
    progress,
    setProgress,
    statusMessage,
    setStatusMessage,
    processError,
    setProcessError,
    canCancelProcessing,
    setCanCancelProcessing,
  };
}

function useProcessingGateState() {
  const [pendingAction, setPendingAction] =
    useState<PendingProcessingAction | null>(null);
  const [stage, setStage] = useState<ProcessingGateStage | null>(null);
  const [scrollPosition, setScrollPosition] = useState<{
    x: number;
    y: number;
  } | null>(null);
  const [error, setError] = useState("");
  const [balanceLoading, setBalanceLoading] = useState(false);
  const [showCreditPurchase, setShowCreditPurchase] = useState(false);
  return {
    pendingAction,
    setPendingAction,
    stage,
    setStage,
    scrollPosition,
    setScrollPosition,
    error,
    setError,
    balanceLoading,
    setBalanceLoading,
    showCreditPurchase,
    setShowCreditPurchase,
  };
}

type Foundation = ReturnType<typeof useDashboardFoundation>;
type CoreProcessingState = ReturnType<typeof useCoreProcessingState>;
type GateState = ReturnType<typeof useProcessingGateState>;

function prepareVideoUpload(
  foundation: Foundation,
  core: CoreProcessingState,
  uploadController: AbortController,
): void {
  reportProductAction("processing_started", { outcome: "started" });
  core.setActiveUpload(uploadController);
  core.setIsProcessing(true);
  core.setCanCancelProcessing(true);
  core.setProcessError("");
  core.setProgress(0);
  foundation.jobs.setSelectedJob(null);
  core.setStatusMessage(foundation.t("statusUploading"));
}

function useProcessingPolling(
  foundation: Foundation,
  core: CoreProcessingState,
) {
  const refreshActivity = useCallback(async () => {
    await foundation.jobs.loadJobs();
  }, [foundation.jobs]);
  const callbacks = useMemo<JobPollingCallbacks>(
    () => ({
      onProgress: (progress: number, message: string) => {
        core.setProgress(progress);
        core.setStatusMessage(message);
      },
      onComplete: (job: JobResponse) => {
        reportProductAction("processing_completed", { outcome: "succeeded" });
        core.setIsProcessing(false);
        core.setCanCancelProcessing(false);
        core.setJobId(null);
        foundation.jobs.setSelectedJob(job);
        core.setProcessError("");
        void refreshActivity();
      },
      onFailed: (errorMessage: string) => {
        reportProductAction("processing_failed", { outcome: "failed" });
        localStorage.removeItem("lastActiveJobId");
        core.setProcessError(
          errorMessage === ELEVENLABS_MISSING_WORD_TIMESTAMPS
            ? foundation.t("transcriptionMissingWordTimestamps")
            : errorMessage,
        );
        core.setIsProcessing(false);
        core.setCanCancelProcessing(false);
        core.setJobId(null);
        void foundation.points.refreshBalance();
        void refreshActivity();
      },
      onError: (errorMessage: string) => {
        core.setIsProcessing(false);
        core.setCanCancelProcessing(false);
        core.setProcessError(errorMessage);
      },
    }),
    [core, foundation, refreshActivity],
  );
  useJobPolling({ jobId: core.jobId, callbacks, t: foundation.t });
  const cancel = useCallback(async () => {
    const activeUpload = core.takeActiveUpload();
    if (activeUpload) {
      activeUpload.abort();
      core.setCanCancelProcessing(false);
      core.setIsProcessing(false);
      core.setProcessError(foundation.t("processingCancelled"));
      return;
    }
    if (!core.jobId) return;
    try {
      await api.cancelJob(core.jobId);
      core.setCanCancelProcessing(false);
      core.setStatusMessage(foundation.t("cancellationRequested"));
      core.setProcessError("");
      await refreshActivity();
    } catch (error) {
      console.error("Cancel failed:", error);
    }
  }, [core, foundation, refreshActivity]);
  return { refreshActivity, cancel };
}

function useProcessingGateBase(
  foundation: Foundation,
  core: CoreProcessingState,
  gate: GateState,
) {
  const captureScrollPosition = useCallback(() => {
    if (typeof window === "undefined") return;
    const bodyIsFixed = document.body.style.position === "fixed";
    const bodyLeft = Number.parseFloat(document.body.style.left);
    const bodyTop = Number.parseFloat(document.body.style.top);
    gate.setScrollPosition({
      x: bodyIsFixed && Number.isFinite(bodyLeft) ? -bodyLeft : window.scrollX,
      y: bodyIsFixed && Number.isFinite(bodyTop) ? -bodyTop : window.scrollY,
    });
  }, [gate]);
  const reopenQuote = useCallback(
    (error: unknown, action: PendingProcessingAction): boolean => {
      const quoteChange = processingQuoteChangeFromError(error);
      if (!quoteChange) return false;
      gate.setPendingAction({
        ...action,
        authorizedCredits: quoteChange.requiredCredits,
      });
      gate.setError(
        foundation.t("processingGateQuoteChanged", {
          duration: quoteChange.durationSeconds,
          cost: quoteChange.requiredCredits,
        }),
      );
      captureScrollPosition();
      gate.setStage("cost");
      core.setProcessError("");
      return true;
    },
    [captureScrollPosition, core, foundation, gate],
  );
  const close = useCallback(() => {
    gate.setStage(null);
    gate.setScrollPosition(null);
    gate.setPendingAction(null);
    gate.setError("");
    gate.setBalanceLoading(false);
  }, [gate]);
  const loadBalance = useCallback(async () => {
    gate.setBalanceLoading(true);
    gate.setError("");
    try {
      foundation.points.setWallet(await api.getPointsBalance());
    } catch (error) {
      gate.setError(
        error instanceof Error ? error.message : foundation.t("creditsError"),
      );
    } finally {
      gate.setBalanceLoading(false);
    }
  }, [foundation, gate]);
  const requestAction = useCallback(
    (action: PendingProcessingAction) => {
      captureScrollPosition();
      gate.setPendingAction(action);
      gate.setError("");
      if (!foundation.auth.user) {
        gate.setStage("auth");
        return;
      }
      gate.setStage("cost");
      void loadBalance();
    },
    [captureScrollPosition, foundation.auth.user, gate, loadBalance],
  );
  return {
    captureScrollPosition,
    reopenQuote,
    close,
    loadBalance,
    requestAction,
  };
}

type GateBase = ReturnType<typeof useProcessingGateBase>;

function useProcessingExecution(
  foundation: Foundation,
  core: CoreProcessingState,
  gateBase: GateBase,
) {
  const start = useCallback(
    async (
      options: ProcessingOptions,
      authorizedCredits: ProcessingCreditTier,
    ) => {
      if (!core.selectedFile) return;
      const uploadController = new AbortController();
      prepareVideoUpload(foundation, core, uploadController);
      const reportUploadProgress = (percent: number) => {
        core.setProgress(percent);
        core.setStatusMessage(`${foundation.t("statusUploading")} ${percent}%`);
      };
      const markUploadComplete = () => {
        core.clearActiveUpload(uploadController);
        core.setCanCancelProcessing(false);
        core.setProgress(0);
        core.setStatusMessage(foundation.t("statusProcessing"));
      };
      try {
        const result = await api.processVideo(
          core.selectedFile,
          processingSettings(options, authorizedCredits, true),
          {
            signal: uploadController.signal,
            onProgress: reportUploadProgress,
            onUploadComplete: markUploadComplete,
          },
        );
        core.setJobId(result.id);
        core.setCanCancelProcessing(true);
        if (typeof result.balance === "number") {
          foundation.points.setBalance(result.balance);
        }
        void foundation.points.refreshBalance();
      } catch (error) {
        void foundation.points.refreshBalance();
        const quoteReopened = gateBase.reopenQuote(error, {
          kind: "new",
          options,
        });
        if (!quoteReopened) {
          core.setProcessError(
            uploadFailureMessage(
              error,
              uploadController.signal.aborted,
              foundation.t,
            ),
          );
        }
        core.setIsProcessing(false);
        core.setCanCancelProcessing(false);
        reportProcessingFailure(uploadController.signal.aborted, quoteReopened);
      } finally {
        core.clearActiveUpload(uploadController);
      }
    },
    [core, foundation, gateBase],
  );
  const reprocess = useCallback(
    async (
      sourceJobId: string,
      options: ProcessingOptions,
      authorizedCredits: ProcessingCreditTier,
    ) => {
      reportProductAction("processing_started", { outcome: "started" });
      core.setIsProcessing(true);
      core.setCanCancelProcessing(false);
      core.setProcessError("");
      core.setProgress(0);
      core.setStatusMessage(foundation.t("statusProcessing"));
      try {
        const result = await api.reprocessJob(
          sourceJobId,
          processingSettings(options, authorizedCredits),
        );
        core.setJobId(result.id);
        core.setCanCancelProcessing(true);
        if (typeof result.balance === "number") {
          foundation.points.setBalance(result.balance);
        }
        void foundation.points.refreshBalance();
      } catch (error) {
        const quoteReopened = gateBase.reopenQuote(error, {
          kind: "reprocess",
          sourceJobId,
          options,
        });
        if (!quoteReopened) {
          core.setProcessError(
            error instanceof Error
              ? error.message
              : foundation.t("startProcessingError"),
          );
          reportProductAction("processing_failed", { outcome: "failed" });
        }
        core.setIsProcessing(false);
        core.setCanCancelProcessing(false);
      }
    },
    [core, foundation, gateBase],
  );
  return { start, reprocess };
}

type ProcessingExecution = ReturnType<typeof useProcessingExecution>;

function useProcessingGateActions(
  foundation: Foundation,
  gate: GateState,
  gateBase: GateBase,
  execution: ProcessingExecution,
) {
  const cost = useMemo(() => {
    if (!gate.pendingAction) return 0;
    return (
      gate.pendingAction.authorizedCredits ??
      processVideoCostForSelection(
        gate.pendingAction.options.transcribeProvider,
        gate.pendingAction.options.transcribeMode,
        gate.pendingAction.options.sourceDurationSeconds,
      )
    );
  }, [gate.pendingAction]);
  const requiresPaidCredits = useMemo(
    () =>
      transcribeProviderRequiresPaidCredits(
        gate.pendingAction?.options.transcribeProvider,
      ),
    [gate.pendingAction],
  );
  const balance = requiresPaidCredits
    ? foundation.points.aiSpendableBalance
    : foundation.points.balance;
  const requestStart = useCallback(
    async (options: ProcessingOptions) => {
      gateBase.requestAction({ kind: "new", options });
    },
    [gateBase],
  );
  const requestReprocess = useCallback(
    async (sourceJobId: string, options: ProcessingOptions) => {
      gateBase.requestAction({ kind: "reprocess", sourceJobId, options });
    },
    [gateBase],
  );
  const authenticated = useCallback(async () => {
    if (!gate.pendingAction) {
      gateBase.close();
      return;
    }
    gate.setStage("cost");
    await gateBase.loadBalance();
  }, [gate, gateBase]);
  const confirm = useCallback(async () => {
    const action = gate.pendingAction;
    if (
      !action ||
      !isProcessingCreditTier(cost) ||
      balance === null ||
      balance < cost
    ) {
      return;
    }
    gateBase.close();
    if (action.kind === "new") {
      await execution.start(action.options, cost);
      return;
    }
    await execution.reprocess(action.sourceJobId, action.options, cost);
  }, [balance, cost, execution, gate.pendingAction, gateBase]);
  return {
    cost,
    requiresPaidCredits,
    balance,
    requestStart,
    requestReprocess,
    authenticated,
    confirm,
  };
}

function useWorkspaceActions(
  foundation: Foundation,
  core: CoreProcessingState,
) {
  const [showHomeConfirm, setShowHomeConfirm] = useState(false);
  const reset = useCallback(() => {
    core.abortActiveUpload();
    core.setSelectedFile(null);
    foundation.jobs.setSelectedJob(null);
    core.setIsProcessing(false);
    core.setCanCancelProcessing(false);
    core.setProgress(0);
    core.setJobId(null);
    core.setStatusMessage("");
    core.setProcessError("");
    localStorage.removeItem("lastActiveJobId");
  }, [core, foundation.jobs]);
  const hasActiveWorkspace = Boolean(
    core.selectedFile ||
    foundation.jobs.selectedJob ||
    core.isProcessing ||
    core.jobId,
  );
  const brandHomeClick = useCallback(
    (event: MouseEvent<HTMLAnchorElement>) => {
      if (!hasActiveWorkspace) return;
      event.preventDefault();
      setShowHomeConfirm(true);
    },
    [hasActiveWorkspace],
  );
  const confirmHome = useCallback(() => {
    reset();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, [reset]);
  const selectFile = useCallback(
    (file: File | null) => {
      core.setSelectedFile(file);
      if (file) {
        foundation.jobs.setSelectedJob(null);
        reportProductAction("file_selected");
      }
    },
    [core, foundation.jobs],
  );
  const refreshJobs = useCallback(async () => {
    await foundation.jobs.loadJobs(false);
  }, [foundation.jobs]);
  return {
    showHomeConfirm,
    setShowHomeConfirm,
    reset,
    brandHomeClick,
    confirmHome,
    selectFile,
    refreshJobs,
  };
}

export function useDashboardController() {
  const foundation = useDashboardFoundation();
  const core = useCoreProcessingState();
  const gate = useProcessingGateState();
  const polling = useProcessingPolling(foundation, core);
  const gateBase = useProcessingGateBase(foundation, core, gate);
  const execution = useProcessingExecution(foundation, core, gateBase);
  const gateActions = useProcessingGateActions(
    foundation,
    gate,
    gateBase,
    execution,
  );
  const workspace = useWorkspaceActions(foundation, core);
  const restorePending = useSessionJobRestore({
    authenticatedUserId: foundation.auth.user?.id ?? null,
    selectedFile: core.selectedFile,
    selectedJob: foundation.jobs.selectedJob,
    jobId: core.jobId,
    setSelectedJob: foundation.jobs.setSelectedJob,
    setJobId: core.setJobId,
    setIsProcessing: core.setIsProcessing,
    setCanCancelProcessing: core.setCanCancelProcessing,
    setProgress: core.setProgress,
    setStatusMessage: core.setStatusMessage,
    setProcessError: core.setProcessError,
    t: foundation.t,
  });
  const closeCreditPurchase = useCallback(() => {
    gate.setShowCreditPurchase(false);
    if (foundation.auth.user) void foundation.points.refreshBalance();
  }, [foundation, gate]);
  return {
    foundation,
    core,
    gate,
    gateBase,
    gateActions,
    polling,
    workspace,
    restorePending,
    closeCreditPurchase,
  };
}

export type DashboardController = ReturnType<typeof useDashboardController>;
