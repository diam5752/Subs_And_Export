"use client";

import { DashboardLoadingScreen } from "@/components/dashboard/DashboardLoadingScreen";
import { DashboardView } from "@/components/dashboard/DashboardView";
import { SessionRecoveryScreen } from "@/components/SessionRecoveryScreen";
import { useDashboardController } from "@/features/process/useDashboardController";

export default function DashboardPage() {
  const controller = useDashboardController();
  if (controller.foundation.auth.sessionUnavailable) {
    return (
      <SessionRecoveryScreen
        onRetry={controller.foundation.auth.retrySession}
      />
    );
  }
  if (controller.foundation.auth.isLoading || controller.restorePending) {
    return <DashboardLoadingScreen />;
  }
  return <DashboardView controller={controller} />;
}
