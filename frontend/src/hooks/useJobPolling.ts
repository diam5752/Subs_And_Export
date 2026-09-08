import { useEffect, useRef, useCallback, useState } from "react";
import { api, JobResponse } from "@/lib/api";
import type { MessageKey } from "@/context/i18nMessages";

export interface JobPollingCallbacks {
  onProgress: (progress: number, message: string) => void;
  onComplete: (job: JobResponse) => void;
  onFailed: (errorMessage: string) => void;
  onError: (errorMessage: string) => void;
}

interface UseJobPollingOptions {
  jobId: string | null;
  callbacks: JobPollingCallbacks;
  pollingInterval?: number;
  t: (key: MessageKey) => string;
}

interface UseJobPollingResult {
  isPolling: boolean;
  stopPolling: () => void;
}

function startPolling(
  jobId: string,
  interval: number,
  onStatus: (job: JobResponse) => void,
  onError: () => void,
): () => void {
  let active = true;
  let inFlight = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const schedule = () => {
    timer = setTimeout(
      () => void poll(),
      document.hidden ? Math.max(interval, 15_000) : interval,
    );
  };
  const poll = async () => {
    if (!active || inFlight) return;
    inFlight = true;
    try {
      const job = await api.getJobStatus(jobId);
      if (active) onStatus(job);
    } catch {
      if (active) onError();
    } finally {
      inFlight = false;
      if (active) schedule();
    }
  };
  const onVisibilityChange = () => {
    clearTimeout(timer);
    if (inFlight || !active) return;
    if (document.hidden) schedule();
    else void poll();
  };
  document.addEventListener("visibilitychange", onVisibilityChange);
  void poll();
  return () => {
    active = false;
    clearTimeout(timer);
    document.removeEventListener("visibilitychange", onVisibilityChange);
  };
}

function reportStatus(
  job: JobResponse,
  { callbacks, t }: Pick<UseJobPollingOptions, "callbacks" | "t">,
  stop: () => void,
): void {
  callbacks.onProgress(
    job.progress,
    job.status === "cancelling"
      ? t("cancellationRequested")
      : job.message ||
          (job.status === "processing" ? t("statusProcessingEllipsis") : ""),
  );
  if (job.status === "completed") {
    stop();
    callbacks.onComplete(job);
  } else if (job.status === "failed") {
    stop();
    callbacks.onFailed(job.message || t("statusFailedFallback"));
  } else if (job.status === "cancelled") {
    stop();
    callbacks.onFailed(t("processingCancelled"));
  }
}

/** Poll sequentially, slow down hidden tabs and ignore obsolete job responses. */
export function useJobPolling({
  jobId,
  callbacks,
  pollingInterval = 1000,
  t,
}: UseJobPollingOptions): UseJobPollingResult {
  const [isPolling, setIsPolling] = useState(false);
  const stopRef = useRef<(() => void) | null>(null);
  const handlers = useRef({ callbacks, t });
  useEffect(() => {
    handlers.current = { callbacks, t };
  }, [callbacks, t]);

  const stopPolling = useCallback(() => {
    stopRef.current?.();
    setIsPolling(false);
  }, []);

  useEffect(() => {
    const starter = setTimeout(() => {
      setIsPolling(Boolean(jobId));
      if (!jobId) return;
      stopRef.current = startPolling(
        jobId,
        pollingInterval,
        (job) => reportStatus(job, handlers.current, stopPolling),
        () => {
          stopPolling();
          handlers.current.callbacks.onError(
            handlers.current.t("statusCheckFailed"),
          );
        },
      );
    }, 0);
    stopRef.current = () => clearTimeout(starter);
    return () => {
      clearTimeout(starter);
      stopRef.current?.();
    };
  }, [jobId, pollingInterval, stopPolling]);

  return { isPolling, stopPolling };
}
