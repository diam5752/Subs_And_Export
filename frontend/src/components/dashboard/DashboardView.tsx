import dynamic from "next/dynamic";
import { BetaLaunchCreditAward } from "@/components/dashboard/BetaLaunchCreditAward";
import { DashboardHeader } from "@/components/dashboard/DashboardHeader";
import { BrandLogo } from "@/components/BrandLogo";
import { ConfirmActionModal } from "@/components/ConfirmActionModal";
import { ProcessView } from "@/features/process/ProcessView";
import type { DashboardController } from "@/features/process/useDashboardController";
import { formatDate, buildStaticUrl } from "@/lib/utils";

// These surfaces are closed during the normal editor render. Keep their form,
// history and focus-management code outside the performance-critical bundle;
// Next loads each surface only when its existing outer guard opens it.
const AccountDialog = dynamic(() =>
  import("@/components/dashboard/AccountDialog").then(
    (module) => module.AccountDialog,
  ),
);

const CheckoutReturnNotice = dynamic(() =>
  import("@/components/CheckoutReturnNotice").then(
    (module) => module.CheckoutReturnNotice,
  ),
);

const ProcessingGateModal = dynamic(() =>
  import("@/components/ProcessingGateModal").then(
    (module) => module.ProcessingGateModal,
  ),
);

const CreditPurchaseDialog = dynamic(() =>
  import("@/components/CreditPurchaseDialog").then(
    (module) => module.CreditPurchaseDialog,
  ),
);

const statusStyles: Record<string, string> = {
  completed: "bg-green-500/15 text-green-300 border-green-500/30",
  processing:
    "bg-[var(--accent)]/15 text-[var(--accent)] border-[var(--accent)]/40",
  pending: "bg-[var(--muted)]/10 text-[var(--muted)] border-[var(--border)]",
  failed:
    "bg-[var(--danger)]/15 text-[var(--danger)] border-[var(--danger)]/40",
};

function StudioMain({ controller }: { controller: DashboardController }) {
  const { foundation, core, gateActions, polling, workspace } = controller;
  return (
    <main
      className={`studio-main ${
        foundation.jobs.selectedJob?.status === "completed"
          ? "studio-main-workspace"
          : ""
      }`}
    >
      <section className="studio-intro" data-testid="studio-intro">
        <div className="studio-intro-copy">
          <h1>{foundation.t("heroTitle")}</h1>
          <p>{foundation.t("heroSubtitle")}</p>
        </div>
      </section>
      {foundation.auth.user && foundation.auth.betaCreditsAwarded > 0 && (
        <BetaLaunchCreditAward
          count={foundation.auth.betaCreditsAwarded}
          onDismiss={foundation.auth.dismissBetaCreditsAwarded}
        />
      )}
      <ProcessView
        selectedFile={core.selectedFile}
        onFileSelect={workspace.selectFile}
        isProcessing={core.isProcessing}
        progress={core.progress}
        statusMessage={core.statusMessage}
        error={core.processError}
        onStartProcessing={gateActions.requestStart}
        onReprocessJob={gateActions.requestReprocess}
        onReset={workspace.reset}
        onCancelProcessing={
          core.canCancelProcessing ? polling.cancel : undefined
        }
        selectedJob={foundation.jobs.selectedJob}
        onJobSelect={foundation.jobs.setSelectedJob}
        onRefreshJobs={polling.refreshActivity}
        statusStyles={statusStyles}
        buildStaticUrl={buildStaticUrl}
        totalJobs={foundation.jobs.totalJobs}
      />
    </main>
  );
}

function StudioFooter({ controller }: { controller: DashboardController }) {
  return (
    <footer className="studio-footer">
      <a
        href="https://ascentia-gp.com/"
        target="_blank"
        rel="noopener noreferrer"
        className="footer-brand"
      >
        <BrandLogo className="block h-auto w-[68px]" />
        <span>
          <small>by Ascentia</small>
        </span>
      </a>
      <p className="studio-beta-note">
        {controller.foundation.t("betaTestingNotice")}
      </p>
      <div className="footer-links">
        <a href="/privacy">{controller.foundation.t("legalPrivacyLink")}</a>
        <a href="/terms">{controller.foundation.t("legalTermsLink")}</a>
      </div>
    </footer>
  );
}

function DashboardStudio({
  controller,
  blocked,
}: {
  controller: DashboardController;
  blocked: boolean;
}) {
  return (
    <div
      className="studio-stage"
      aria-hidden={blocked || undefined}
      inert={blocked ? true : undefined}
    >
      <StudioMain controller={controller} />
      <StudioFooter controller={controller} />
    </div>
  );
}

function ProcessingGateLayer({
  controller,
}: {
  controller: DashboardController;
}) {
  const { foundation, gate, gateBase, gateActions } = controller;
  if (gate.stage === null || gate.showCreditPurchase) return null;
  return (
    <ProcessingGateModal
      isOpen
      stage={gate.stage}
      initialScrollPosition={gate.scrollPosition ?? undefined}
      cost={gateActions.cost}
      balance={gateActions.balance}
      requiresPaidCredits={gateActions.requiresPaidCredits}
      isBalanceLoading={gate.balanceLoading}
      error={gate.error}
      onClose={gateBase.close}
      onAuthenticated={gateActions.authenticated}
      onConfirm={gateActions.confirm}
      onPurchaseCredits={
        foundation.paidCreditSalesUiApproved
          ? () => gate.setShowCreditPurchase(true)
          : undefined
      }
    />
  );
}

function CreditPurchaseLayer({
  controller,
}: {
  controller: DashboardController;
}) {
  const { foundation, gate, gateActions, gateBase } = controller;
  if (!foundation.paidCreditSalesUiApproved || !gate.showCreditPurchase) {
    return null;
  }
  const requireAuth = () => {
    gateBase.captureScrollPosition();
    gate.setShowCreditPurchase(false);
    gate.setStage("auth");
  };
  return (
    <CreditPurchaseDialog
      isOpen
      isAuthenticated={Boolean(foundation.auth.user)}
      requiredCredits={gateActions.cost}
      onClose={controller.closeCreditPurchase}
      onRequireAuth={requireAuth}
    />
  );
}

function HomeConfirmLayer({ controller }: { controller: DashboardController }) {
  if (!controller.workspace.showHomeConfirm) return null;
  const { t } = controller.foundation;
  return (
    <ConfirmActionModal
      isOpen
      title={t("homeNavigationModalTitle")}
      description={t("homeNavigationModalDesc")}
      cancelLabel={t("homeNavigationCancel")}
      confirmLabel={t("homeNavigationConfirm")}
      onClose={() => controller.workspace.setShowHomeConfirm(false)}
      onConfirm={controller.workspace.confirmHome}
    />
  );
}

function CheckoutReturnLayer({
  controller,
  blocked,
}: {
  controller: DashboardController;
  blocked: boolean;
}) {
  const { checkout } = controller.foundation;
  if (!checkout.notice.message) return null;
  return (
    <CheckoutReturnNotice
      message={checkout.notice.message}
      kind={checkout.notice.kind}
      isInert={blocked}
      canRetry={checkout.canRetry}
      contractAvailable={checkout.contractAvailable}
      onRetry={checkout.retry}
      onDismiss={checkout.dismiss}
    />
  );
}

function AccountLayer({ controller }: { controller: DashboardController }) {
  const { foundation, workspace } = controller;
  const { account, auth, jobs } = foundation;
  if (!auth.user || !account.isOpen) return null;
  return (
    <AccountDialog
      user={auth.user}
      activeTab={account.activeTab}
      returnFocusRef={account.returnFocusRef}
      accountMessage={account.message}
      accountError={account.error}
      accountSaving={account.isSaving}
      recentJobs={jobs.recentJobs}
      jobsLoading={jobs.jobsLoading}
      selectedJobId={jobs.selectedJob?.id}
      currentPage={jobs.currentPage}
      totalPages={jobs.totalPages}
      totalJobs={jobs.totalJobs}
      pageSize={jobs.pageSize}
      onClose={account.close}
      onTabChange={account.setActiveTab}
      onSaveProfile={account.saveProfile}
      onLogout={account.logoutFromAccount}
      onJobSelect={jobs.setSelectedJob}
      onRefreshJobs={workspace.refreshJobs}
      formatDate={formatDate}
      buildStaticUrl={buildStaticUrl}
      setShowPreview={account.showPreview}
      onNextPage={jobs.nextPage}
      onPrevPage={jobs.prevPage}
    />
  );
}

function DashboardModalLayers({
  controller,
}: {
  controller: DashboardController;
}) {
  return (
    <>
      <ProcessingGateLayer controller={controller} />
      <CreditPurchaseLayer controller={controller} />
      <HomeConfirmLayer controller={controller} />
      <AccountLayer controller={controller} />
    </>
  );
}

export function DashboardView({
  controller,
}: {
  controller: DashboardController;
}) {
  const { foundation, core, gate, workspace } = controller;
  const blocked =
    foundation.account.isOpen ||
    gate.stage !== null ||
    (foundation.paidCreditSalesUiApproved && gate.showCreditPurchase) ||
    workspace.showHomeConfirm;
  const uploadLanding =
    !core.selectedFile &&
    !foundation.jobs.selectedJob &&
    !core.isProcessing &&
    !core.jobId &&
    foundation.auth.betaCreditsAwarded === 0 &&
    !foundation.checkout.notice.message;
  return (
    <div
      className={`app-shell min-h-dvh relative overflow-x-hidden ${
        uploadLanding ? "app-shell-upload-landing" : ""
      }`}
    >
      <DashboardHeader
        user={foundation.auth.user}
        isInert={blocked}
        paidCreditSalesUiApproved={foundation.paidCreditSalesUiApproved}
        accountPanelOpen={foundation.account.isOpen}
        accountReturnFocusRef={foundation.account.returnFocusRef}
        onBrandHomeClick={workspace.brandHomeClick}
        onOpenCreditPurchase={() => gate.setShowCreditPurchase(true)}
        onOpenAccount={foundation.account.openProfile}
      />
      <CheckoutReturnLayer controller={controller} blocked={blocked} />
      <DashboardStudio controller={controller} blocked={blocked} />
      <DashboardModalLayers controller={controller} />
    </div>
  );
}
