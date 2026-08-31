import type React from "react";
import type { useI18n } from "@/context/I18nContext";

type Translate = ReturnType<typeof useI18n>["t"];

interface AuthFieldProps {
  id: string;
  label: string;
  type: "text" | "email" | "password";
  value: string;
  autoComplete: string;
  onChange: (value: string) => void;
  inputRef?: React.RefObject<HTMLInputElement | null>;
  minLength?: number;
}

function AuthField({
  id,
  label,
  type,
  value,
  autoComplete,
  onChange,
  inputRef,
  minLength,
}: AuthFieldProps) {
  return (
    <div>
      <label htmlFor={id} className="auth-label">
        {label}
      </label>
      <input
        ref={inputRef}
        id={id}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="input-field"
        autoComplete={autoComplete}
        minLength={minLength}
        required
      />
    </div>
  );
}

interface ProcessingGateAuthFieldsProps {
  isRegistration: boolean;
  name: string;
  email: string;
  password: string;
  emailRef: React.RefObject<HTMLInputElement | null>;
  onNameChange: (value: string) => void;
  onEmailChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  t: Translate;
}

export function ProcessingGateAuthFields(props: ProcessingGateAuthFieldsProps) {
  return (
    <>
      {props.isRegistration && (
        <AuthField
          id="gate-name"
          label={props.t("registerNameLabel")}
          type="text"
          value={props.name}
          autoComplete="name"
          onChange={props.onNameChange}
        />
      )}
      <AuthField
        id="gate-email"
        label={props.t("loginEmailLabel")}
        type="email"
        value={props.email}
        autoComplete="email"
        inputRef={props.emailRef}
        onChange={props.onEmailChange}
      />
      <AuthField
        id="gate-password"
        label={props.t("loginPasswordLabel")}
        type="password"
        value={props.password}
        autoComplete={
          props.isRegistration ? "new-password" : "current-password"
        }
        minLength={props.isRegistration ? 12 : undefined}
        onChange={props.onPasswordChange}
      />
    </>
  );
}
