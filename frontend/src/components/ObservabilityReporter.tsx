"use client";

import { useEffect } from "react";
import { useAuth } from "@/context/AuthContext";
import {
  reportBrowserError,
  reportPresence,
  reportProductAction,
} from "@/lib/observability";

const PRESENCE_INTERVAL_MS = 30_000;

export function ObservabilityReporter() {
  const { user, isLoading } = useAuth();

  useEffect(() => {
    reportProductAction("app_opened");
    const handleError = () => reportBrowserError("window_error");
    const handleRejection = () => reportBrowserError("unhandled_rejection");
    window.addEventListener("error", handleError);
    window.addEventListener("unhandledrejection", handleRejection);
    return () => {
      window.removeEventListener("error", handleError);
      window.removeEventListener("unhandledrejection", handleRejection);
    };
  }, []);

  useEffect(() => {
    if (isLoading) return;
    const heartbeat = () => {
      if (document.visibilityState === "visible") reportPresence();
    };
    heartbeat();
    const interval = window.setInterval(heartbeat, PRESENCE_INTERVAL_MS);
    document.addEventListener("visibilitychange", heartbeat);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", heartbeat);
    };
  }, [isLoading, user?.id]);

  return null;
}
