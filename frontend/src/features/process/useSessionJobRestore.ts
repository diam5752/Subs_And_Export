"use client";

import {
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import type { MessageKey } from "@/context/i18nMessages";
import { api, type JobResponse } from "@/lib/api";
import {
  CANCELLABLE_JOB_STATUSES,
  RESTORABLE_ACTIVE_JOB_STATUSES,
} from "./dashboardProcessing";

type Translate = (
  key: MessageKey,
  params?: Record<string, string | number>,
) => string;
type StateSetter<T> = Dispatch<SetStateAction<T>>;

interface SessionJobRestoreOptions {
  authenticatedUserId: string | null;
  selectedFile: File | null;
  selectedJob: JobResponse | null;
  jobId: string | null;
  setSelectedJob: (job: JobResponse | null) => void;
  setJobId: StateSetter<string | null>;
  setIsProcessing: StateSetter<boolean>;
  setCanCancelProcessing: StateSetter<boolean>;
  setProgress: StateSetter<number>;
  setStatusMessage: StateSetter<string>;
  setProcessError: StateSetter<string>;
  t: Translate;
}

export function useSessionJobRestore({
  authenticatedUserId,
  selectedFile,
  selectedJob,
  jobId,
  setSelectedJob,
  setJobId,
  setIsProcessing,
  setCanCancelProcessing,
  setProgress,
  setStatusMessage,
  setProcessError,
  t,
}: SessionJobRestoreOptions): boolean {
  const attemptedUserIdRef = useRef<string | null>(null);
  const requestGenerationRef = useRef(0);
  const [storedJobId, setStoredJobId] = useState<string | null>(() =>
    typeof window === "undefined"
      ? null
      : localStorage.getItem("lastActiveJobId"),
  );

  useEffect(() => {
    if (!authenticatedUserId) {
      attemptedUserIdRef.current = null;
      requestGenerationRef.current += 1;
      return;
    }
    if (!storedJobId) return;
    if (selectedFile) {
      requestGenerationRef.current += 1;
      queueMicrotask(() => setStoredJobId(null));
      return;
    }
    if (attemptedUserIdRef.current === authenticatedUserId) return;
    attemptedUserIdRef.current = authenticatedUserId;
    const generation = requestGenerationRef.current + 1;
    requestGenerationRef.current = generation;
    const restoreJobId = storedJobId;

    void api
      .getJobStatus(restoreJobId)
      .then((job) => {
        if (generation !== requestGenerationRef.current) return;
        const completedFilesAreAvailable =
          job.status !== "completed" ||
          Boolean(job.result_data && !job.result_data.files_missing);
        setStoredJobId(null);
        if (RESTORABLE_ACTIVE_JOB_STATUSES.has(job.status)) {
          setJobId(job.id);
          setIsProcessing(true);
          setCanCancelProcessing(CANCELLABLE_JOB_STATUSES.has(job.status));
          setProgress(job.progress ?? 0);
          setStatusMessage(
            job.status === "cancelling"
              ? t("cancellationRequested")
              : job.message || t("statusProcessingEllipsis"),
          );
          setProcessError("");
        } else if (job.status === "completed" && completedFilesAreAvailable) {
          setSelectedJob(job);
        } else {
          localStorage.removeItem("lastActiveJobId");
        }
      })
      .catch((restoreError) => {
        if (generation !== requestGenerationRef.current) return;
        console.warn("Failed to restore session job:", restoreError);
        localStorage.removeItem("lastActiveJobId");
        setStoredJobId(null);
      });
  }, [
    authenticatedUserId,
    selectedFile,
    setCanCancelProcessing,
    setIsProcessing,
    setJobId,
    setProcessError,
    setProgress,
    setSelectedJob,
    setStatusMessage,
    storedJobId,
    t,
  ]);

  useEffect(() => {
    const restorableJobId = jobId ?? selectedJob?.id;
    if (restorableJobId)
      localStorage.setItem("lastActiveJobId", restorableJobId);
  }, [jobId, selectedJob]);

  return Boolean(
    authenticatedUserId &&
    storedJobId &&
    !selectedFile &&
    !selectedJob &&
    !jobId,
  );
}
