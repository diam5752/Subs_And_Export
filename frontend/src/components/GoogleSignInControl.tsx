"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type MutableRefObject,
  type RefObject,
} from "react";
import { useAuth } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import { api } from "@/lib/api";
import {
  loadGoogleIdentityScript,
  reloadGoogleIdentityPage,
  type GoogleCredentialResponse,
} from "@/lib/googleIdentity";
import { isEmbeddedMobileBrowser } from "@/lib/embeddedBrowser";
import { Spinner } from "@/components/Spinner";

type GoogleRecoveryReason = "expired" | "failed";

type GoogleRecoveryStrategy = "reload-page" | "reinitialize";

type BrowserSupport = "checking" | "supported" | "embedded";

type CopyState = "idle" | "copied" | "failed";

type GoogleControlStatus = {
  error: string;
  loading: boolean;
  ready: boolean;
  unavailable: boolean;
  recoveryReason: GoogleRecoveryReason | null;
  copyState: CopyState;
};

type GoogleSignInControlProps = {
  onAuthenticated: () => void | Promise<void>;
  recoveryStrategy?: GoogleRecoveryStrategy;
};

const GOOGLE_NONCE_REQUEST_SAFETY_MS = 1_000;
const GOOGLE_NONCE_REJECTION_MESSAGES = new Set([
  "Google login nonce is required.",
  "Google login nonce could not be verified.",
]);

const INITIAL_GOOGLE_CONTROL_STATUS: GoogleControlStatus = {
  error: "",
  loading: false,
  ready: false,
  unavailable: false,
  recoveryReason: null,
  copyState: "idle",
};

function googleNonceUsableDurationMs(expiresInSeconds: number): number {
  const ttlMilliseconds = Math.floor(expiresInSeconds * 1_000);
  if (!Number.isFinite(ttlMilliseconds) || ttlMilliseconds <= 0) {
    return 0;
  }
  const safetyWindow = Math.min(
    GOOGLE_NONCE_REQUEST_SAFETY_MS,
    Math.floor(ttlMilliseconds / 10),
  );
  return ttlMilliseconds - safetyWindow;
}

function isGoogleNonceRejection(error: unknown): boolean {
  return (
    error instanceof Error && GOOGLE_NONCE_REJECTION_MESSAGES.has(error.message)
  );
}

function isCurrentGoogleGeneration(expected: number, current: number): boolean {
  return expected === current;
}

function googleButtonWidth(container: HTMLDivElement): number {
  const availableWidth = container.getBoundingClientRect().width || 320;
  return Math.max(240, Math.min(360, Math.floor(availableWidth)));
}

type Translate = ReturnType<typeof useI18n>["t"];

function useGoogleControlStatus() {
  const [status, setStatus] = useState(INITIAL_GOOGLE_CONTROL_STATUS);
  const updateStatus = useCallback((patch: Partial<GoogleControlStatus>) => {
    setStatus((current) => ({ ...current, ...patch }));
  }, []);
  return [status, updateStatus] as const;
}

function useGoogleMessages(t: Translate) {
  return {
    unavailable: t("loginGoogleUnavailable"),
    error: t("loginErrorGoogle"),
    expired: t("loginGoogleExpired"),
  };
}

function useGoogleI18n() {
  const { t } = useI18n();
  return [t, useGoogleMessages(t)] as const;
}

function subscribeToBrowserSupport(): () => void {
  return () => undefined;
}

function embeddedBrowserSupportSnapshot(): BrowserSupport {
  const navigatorWithStandalone = navigator as Navigator & {
    standalone?: boolean;
  };
  return isEmbeddedMobileBrowser(
    navigator.userAgent,
    navigatorWithStandalone.standalone === true,
  )
    ? "embedded"
    : "supported";
}

function useEmbeddedBrowserSupport(): BrowserSupport {
  return useSyncExternalStore(
    subscribeToBrowserSupport,
    embeddedBrowserSupportSnapshot,
    () => "checking",
  );
}

function useLatest<T>(value: T): MutableRefObject<T> {
  const valueRef = useRef(value);
  useEffect(() => {
    valueRef.current = value;
  }, [value]);
  return valueRef;
}

function EmbeddedGoogleFallback({
  copyState,
  onCopy,
  t,
}: {
  copyState: CopyState;
  onCopy: () => Promise<void>;
  t: Translate;
}) {
  return (
    <div
      className="auth-google-embedded"
      data-testid="google-embedded-browser-fallback"
    >
      <span className="auth-google-embedded-title">
        {t("loginGoogleEmbeddedTitle")}
      </span>
      <span>{t("loginGoogleEmbeddedBody")}</span>
      <button
        type="button"
        onClick={() => void onCopy()}
        className="auth-google-embedded-copy"
      >
        {t("loginGoogleEmbeddedCopy")}
      </button>
      {copyState !== "idle" && (
        <span
          className="auth-google-embedded-result"
          role="status"
          aria-live="polite"
        >
          {copyState === "copied"
            ? t("loginGoogleEmbeddedCopied")
            : t("loginGoogleEmbeddedCopyFailed")}
        </span>
      )}
    </div>
  );
}

function GoogleRecoveryNotice({
  reason,
  expiredMessage,
  errorMessage,
  onRecovery,
  t,
}: {
  reason: GoogleRecoveryReason;
  expiredMessage: string;
  errorMessage: string;
  onRecovery: () => void;
  t: Translate;
}) {
  return (
    <div
      className="auth-google-unavailable flex-col gap-2 text-center"
      role="status"
      aria-live="polite"
    >
      <span>{reason === "expired" ? expiredMessage : errorMessage}</span>
      <button
        type="button"
        onClick={onRecovery}
        className="font-semibold text-[var(--accent)] underline underline-offset-2"
      >
        {t("loginGoogleReload")}
      </button>
    </div>
  );
}

function GoogleButtonShell({
  containerRef,
  googleReady,
  googleLoading,
  t,
}: {
  containerRef: RefObject<HTMLDivElement | null>;
  googleReady: boolean;
  googleLoading: boolean;
  t: Translate;
}) {
  return (
    <div
      className="auth-google-shell"
      aria-busy={!googleReady || googleLoading}
    >
      <div
        ref={containerRef}
        className={
          googleReady ? "auth-google-official is-ready" : "auth-google-official"
        }
        data-testid="google-button-container"
      />
      {(!googleReady || googleLoading) && (
        <div className="auth-google-placeholder" aria-hidden={googleReady}>
          <Spinner className="w-5 h-5 text-gray-600" />
          <span>
            {googleLoading ? t("loginGoogleSigningIn") : t("loginGoogleCta")}
          </span>
        </div>
      )}
    </div>
  );
}

function GoogleControlState({
  browserSupport,
  copyState,
  googleRecoveryReason,
  googleUnavailable,
  googleUnavailableMessage,
  googleExpiredMessage,
  googleErrorMessage,
  googleReady,
  googleLoading,
  containerRef,
  onCopy,
  onRecovery,
  t,
}: {
  browserSupport: BrowserSupport;
  copyState: CopyState;
  googleRecoveryReason: GoogleRecoveryReason | null;
  googleUnavailable: boolean;
  googleUnavailableMessage: string;
  googleExpiredMessage: string;
  googleErrorMessage: string;
  googleReady: boolean;
  googleLoading: boolean;
  containerRef: RefObject<HTMLDivElement | null>;
  onCopy: () => Promise<void>;
  onRecovery: () => void;
  t: Translate;
}) {
  if (browserSupport === "embedded") {
    return (
      <EmbeddedGoogleFallback copyState={copyState} onCopy={onCopy} t={t} />
    );
  }
  if (googleRecoveryReason) {
    return (
      <GoogleRecoveryNotice
        reason={googleRecoveryReason}
        expiredMessage={googleExpiredMessage}
        errorMessage={googleErrorMessage}
        onRecovery={onRecovery}
        t={t}
      />
    );
  }
  if (googleUnavailable) {
    return (
      <div className="auth-google-unavailable" role="status">
        {googleUnavailableMessage}
      </div>
    );
  }
  return (
    <GoogleButtonShell
      containerRef={containerRef}
      googleReady={googleReady}
      googleLoading={googleLoading}
      t={t}
    />
  );
}

function useGoogleSignInController({
  onAuthenticated,
  recoveryStrategy = "reload-page",
}: GoogleSignInControlProps) {
  const [status, updateStatus] = useGoogleControlStatus();
  const [initializationAttempt, setInitializationAttempt] = useState(0);
  const browserSupport = useEmbeddedBrowserSupport();
  const { googleLogin } = useAuth();
  const [t, messages] = useGoogleI18n();
  const googleButtonContainerRef = useRef<HTMLDivElement>(null);
  const googleNonceUsableUntilRef = useRef(0);
  const googleCredentialSubmittedRef = useRef(false);
  const googleInitializationGenerationRef = useRef(0);

  const requireFreshGooglePage = useCallback(
    (reason: GoogleRecoveryReason) => {
      googleNonceUsableUntilRef.current = 0;
      googleCredentialSubmittedRef.current = true;
      googleButtonContainerRef.current?.replaceChildren();
      updateStatus({
        ready: false,
        loading: false,
        unavailable: false,
        recoveryReason: reason,
      });
    },
    [updateStatus],
  );

  const handleGoogleCredential = useCallback(
    async (
      credentialResponse: GoogleCredentialResponse,
      initializationGeneration: number,
    ) => {
      const isCurrentGeneration = () =>
        isCurrentGoogleGeneration(
          initializationGeneration,
          googleInitializationGenerationRef.current,
        );
      if (!isCurrentGeneration()) {
        return;
      }
      if (!credentialResponse.credential) {
        updateStatus({ error: messages.error });
        return;
      }
      if (googleCredentialSubmittedRef.current) {
        return;
      }
      if (
        googleNonceUsableUntilRef.current === 0 ||
        Date.now() >= googleNonceUsableUntilRef.current
      ) {
        requireFreshGooglePage("expired");
        return;
      }
      googleCredentialSubmittedRef.current = true;
      updateStatus({ error: "", loading: true });
      try {
        await googleLogin(credentialResponse.credential);
        if (!isCurrentGeneration()) {
          return;
        }
        await onAuthenticated();
      } catch (err) {
        if (!isCurrentGeneration()) {
          return;
        }
        if (isGoogleNonceRejection(err)) {
          requireFreshGooglePage("expired");
        } else {
          updateStatus({
            error: err instanceof Error ? err.message : messages.error,
          });
          requireFreshGooglePage("failed");
        }
      } finally {
        if (isCurrentGeneration()) {
          updateStatus({ loading: false });
        }
      }
    },
    [
      googleLogin,
      messages.error,
      onAuthenticated,
      requireFreshGooglePage,
      updateStatus,
    ],
  );
  const handleGoogleCredentialRef = useLatest(handleGoogleCredential);

  useEffect(() => {
    if (browserSupport !== "supported") {
      return;
    }
    const container = googleButtonContainerRef.current;
    if (!container) {
      return;
    }
    const googleButtonContainer = container;

    let cancelled = false;
    let expiryTimeoutId: number | undefined;
    const abortController = new AbortController();
    const initializationGeneration =
      googleInitializationGenerationRef.current + 1;
    googleInitializationGenerationRef.current = initializationGeneration;
    googleButtonContainer.replaceChildren();
    googleNonceUsableUntilRef.current = 0;
    googleCredentialSubmittedRef.current = false;
    updateStatus({
      error: "",
      ready: false,
      unavailable: false,
      recoveryReason: null,
    });

    async function initializeGoogle() {
      const isCurrentGeneration = () =>
        isCurrentGoogleGeneration(
          initializationGeneration,
          googleInitializationGenerationRef.current,
        );
      try {
        const nonce = await api.getGoogleAuthNonce(abortController.signal);
        if (cancelled || !isCurrentGeneration()) {
          return;
        }
        const clientId = nonce.client_id.trim();
        if (!clientId) {
          throw new Error("Google login is unavailable.");
        }
        const nonceUsableDuration = googleNonceUsableDurationMs(
          nonce.expires_in,
        );
        if (nonceUsableDuration === 0) {
          throw new Error("Google login is unavailable.");
        }
        googleNonceUsableUntilRef.current = Date.now() + nonceUsableDuration;
        expiryTimeoutId = window.setTimeout(() => {
          if (!cancelled && !googleCredentialSubmittedRef.current) {
            requireFreshGooglePage("expired");
          }
        }, nonceUsableDuration);
        await loadGoogleIdentityScript();
        if (cancelled || !isCurrentGeneration()) {
          return;
        }
        if (Date.now() >= googleNonceUsableUntilRef.current) {
          requireFreshGooglePage("expired");
          return;
        }
        const googleId = window.google?.accounts?.id;
        if (!googleId?.initialize || !googleId.renderButton) {
          throw new Error("Google login is unavailable.");
        }
        googleId.initialize({
          client_id: clientId,
          nonce: nonce.nonce,
          ux_mode: "popup",
          callback: (response: GoogleCredentialResponse) => {
            if (!isCurrentGeneration()) {
              return;
            }
            void handleGoogleCredentialRef.current(
              response,
              initializationGeneration,
            );
          },
        });
        const width = googleButtonWidth(googleButtonContainer);
        googleId.renderButton(googleButtonContainer, {
          type: "standard",
          theme: "outline",
          size: "large",
          text: "signin_with",
          shape: "rectangular",
          logo_alignment: "left",
          width,
          locale: "el",
        });
        updateStatus({ ready: true });
      } catch {
        if (
          !cancelled &&
          isCurrentGeneration() &&
          !googleCredentialSubmittedRef.current
        ) {
          googleNonceUsableUntilRef.current = 0;
          googleCredentialSubmittedRef.current = true;
          updateStatus({ unavailable: true, recoveryReason: null, error: "" });
        }
      }
    }

    void initializeGoogle();
    return () => {
      cancelled = true;
      abortController.abort();
      if (
        googleInitializationGenerationRef.current === initializationGeneration
      ) {
        googleInitializationGenerationRef.current += 1;
      }
      if (expiryTimeoutId !== undefined) {
        window.clearTimeout(expiryTimeoutId);
      }
      googleNonceUsableUntilRef.current = 0;
      googleCredentialSubmittedRef.current = true;
      googleButtonContainer.replaceChildren();
    };
  }, [
    browserSupport,
    handleGoogleCredentialRef,
    initializationAttempt,
    requireFreshGooglePage,
    updateStatus,
  ]);

  const handleCopyLoginLink = async () => {
    const loginUrl = new URL("/login", window.location.origin).toString();
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error("Clipboard API unavailable.");
      }
      await navigator.clipboard.writeText(loginUrl);
      updateStatus({ copyState: "copied" });
    } catch {
      updateStatus({ copyState: "failed" });
    }
  };

  const handleRecovery = () => {
    if (recoveryStrategy === "reload-page") {
      reloadGoogleIdentityPage();
      return;
    }
    updateStatus({ recoveryReason: null, unavailable: false });
    setInitializationAttempt((attempt) => attempt + 1);
  };

  return {
    browserSupport,
    status,
    messages,
    googleButtonContainerRef,
    handleCopyLoginLink,
    handleRecovery,
    t,
  };
}

function GoogleSignInView({
  controller,
}: {
  controller: ReturnType<typeof useGoogleSignInController>;
}) {
  return (
    <>
      <GoogleControlState
        browserSupport={controller.browserSupport}
        copyState={controller.status.copyState}
        googleRecoveryReason={controller.status.recoveryReason}
        googleUnavailable={controller.status.unavailable}
        googleUnavailableMessage={controller.messages.unavailable}
        googleExpiredMessage={controller.messages.expired}
        googleErrorMessage={controller.messages.error}
        googleReady={controller.status.ready}
        googleLoading={controller.status.loading}
        containerRef={controller.googleButtonContainerRef}
        onCopy={controller.handleCopyLoginLink}
        onRecovery={controller.handleRecovery}
        t={controller.t}
      />
      {controller.status.error && (
        <div className="auth-error">{controller.status.error}</div>
      )}
    </>
  );
}

export function GoogleSignInControl(props: GoogleSignInControlProps) {
  const controller = useGoogleSignInController(props);
  return <GoogleSignInView controller={controller} />;
}
