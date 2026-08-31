import { Spinner } from "@/components/Spinner";
import type { useI18n } from "@/context/I18nContext";
import { ProcessingGateLegalNotice } from "./ProcessingGateLegalNotice";

type Translate = ReturnType<typeof useI18n>["t"];

interface ProcessingGateAuthActionsProps {
  isRegistration: boolean;
  isSubmitting: boolean;
  authError: string;
  error: string;
  onToggleMode: () => void;
  t: Translate;
}

export function ProcessingGateAuthActions(
  props: ProcessingGateAuthActionsProps,
) {
  const message = props.authError || props.error;
  return (
    <>
      {message && (
        <p
          role="alert"
          className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          {message}
        </p>
      )}
      {props.isRegistration && <ProcessingGateLegalNotice t={props.t} />}
      <button
        type="submit"
        disabled={props.isSubmitting}
        aria-busy={props.isSubmitting}
        aria-describedby={
          props.isRegistration
            ? "processing-gate-register-legal-notice"
            : undefined
        }
        className="btn-primary flex min-h-12 w-full items-center justify-center gap-2 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {props.isSubmitting && <Spinner className="h-4 w-4" />}
        {props.isRegistration
          ? props.t("processingGateRegisterSubmit")
          : props.t("processingGateLoginSubmit")}
      </button>
      <button
        type="button"
        onClick={props.onToggleMode}
        className="min-h-11 w-full text-sm font-semibold text-[var(--foreground)] hover:text-[var(--accent)]"
      >
        {props.isRegistration
          ? props.t("processingGateUseLogin")
          : props.t("processingGateCreateAccount")}
      </button>
    </>
  );
}
