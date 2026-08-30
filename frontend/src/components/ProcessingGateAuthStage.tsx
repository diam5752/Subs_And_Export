import dynamic from "next/dynamic";
import type React from "react";
import type { useI18n } from "@/context/I18nContext";
import { ProcessingGateAuthActions } from "./ProcessingGateAuthActions";
import { ProcessingGateAuthFields } from "./ProcessingGateAuthFields";

const GoogleSignInControl = dynamic(() =>
  import("@/components/GoogleSignInControl").then(
    (module) => module.GoogleSignInControl,
  ),
);

type Translate = ReturnType<typeof useI18n>["t"];

interface ProcessingGateAuthStageProps {
  authMode: "login" | "register";
  name: string;
  email: string;
  password: string;
  authError: string;
  error: string;
  isSubmitting: boolean;
  emailRef: React.RefObject<HTMLInputElement | null>;
  onAuthenticated: () => Promise<void>;
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
  onNameChange: (value: string) => void;
  onEmailChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onToggleMode: () => void;
  t: Translate;
}

export function ProcessingGateAuthStage(props: ProcessingGateAuthStageProps) {
  const isRegistration = props.authMode === "register";
  return (
    <div className="space-y-4">
      <GoogleSignInControl
        onAuthenticated={props.onAuthenticated}
        recoveryStrategy="reinitialize"
      />
      <div className="auth-divider !my-0">
        <span>{props.t("loginOrEmail")}</span>
      </div>
      <form onSubmit={props.onSubmit} className="space-y-4">
        <ProcessingGateAuthFields
          isRegistration={isRegistration}
          name={props.name}
          email={props.email}
          password={props.password}
          emailRef={props.emailRef}
          onNameChange={props.onNameChange}
          onEmailChange={props.onEmailChange}
          onPasswordChange={props.onPasswordChange}
          t={props.t}
        />
        <ProcessingGateAuthActions
          isRegistration={isRegistration}
          isSubmitting={props.isSubmitting}
          authError={props.authError}
          error={props.error}
          onToggleMode={props.onToggleMode}
          t={props.t}
        />
      </form>
    </div>
  );
}
