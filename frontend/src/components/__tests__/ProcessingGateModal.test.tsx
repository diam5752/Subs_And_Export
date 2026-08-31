import React from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import "@testing-library/jest-dom";
import { ProcessingGateModal } from "@/components/ProcessingGateModal";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";
import {
  loadGoogleIdentityScript,
  reloadGoogleIdentityPage,
  type GoogleCredentialResponse,
} from "@/lib/googleIdentity";

jest.mock("@/context/AuthContext", () => ({
  useAuth: jest.fn(),
}));

jest.mock("@/lib/api", () => ({
  api: {
    getGoogleAuthNonce: jest.fn(),
  },
}));

jest.mock("@/lib/googleIdentity", () => ({
  loadGoogleIdentityScript: jest.fn(),
  reloadGoogleIdentityPage: jest.fn(),
}));

jest.mock("@/context/I18nContext", () => ({
  useI18n: () => ({ t: (key: string) => key }),
}));

describe("ProcessingGateModal", () => {
  const login = jest.fn();
  const register = jest.fn();
  const googleLogin = jest.fn();
  const onAuthenticated = jest.fn();
  const onConfirm = jest.fn();
  const onClose = jest.fn();
  const scrollTo = jest.fn();
  let googleCallback:
    ((response: GoogleCredentialResponse) => void) | undefined;

  beforeEach(() => {
    jest.clearAllMocks();
    Object.defineProperty(window, "scrollTo", {
      configurable: true,
      value: scrollTo,
      writable: true,
    });
    Object.defineProperty(window, "scrollX", {
      configurable: true,
      value: 0,
    });
    Object.defineProperty(window, "scrollY", {
      configurable: true,
      value: 0,
    });
    document.documentElement.removeAttribute("style");
    document.body.removeAttribute("style");
    login.mockResolvedValue(undefined);
    register.mockResolvedValue(undefined);
    googleLogin.mockResolvedValue(undefined);
    onAuthenticated.mockResolvedValue(undefined);
    onConfirm.mockResolvedValue(undefined);
    (useAuth as jest.Mock).mockReturnValue({ login, register, googleLogin });
    (api.getGoogleAuthNonce as jest.Mock).mockResolvedValue({
      nonce: "modal-nonce",
      expires_in: 600,
      client_id: "google-client-id",
    });
    (loadGoogleIdentityScript as jest.Mock).mockResolvedValue(undefined);
    googleCallback = undefined;
    window.google = {
      accounts: {
        id: {
          initialize: jest.fn((options) => {
            googleCallback = options.callback;
          }),
          renderButton: jest.fn((parent) => {
            const button = document.createElement("button");
            button.textContent = "official-google-button";
            parent.appendChild(button);
          }),
        },
      },
    };
  });

  afterEach(() => {
    jest.useRealTimers();
    document.documentElement.removeAttribute("style");
    document.body.removeAttribute("style");
    delete window.google;
  });

  // REGRESSION: iOS Safari and Gmail's in-app WebView can keep scrolling the
  // root document when only body overflow is hidden behind a fixed modal.
  it("locks both root scrollers and restores the exact page position and styles", () => {
    const initialScrollPosition = { x: 17, y: 240 };
    // WebKit may adjust the live viewport between the click and the modal
    // commit. The click-time snapshot remains authoritative.
    Object.defineProperty(window, "scrollX", { configurable: true, value: 31 });
    Object.defineProperty(window, "scrollY", {
      configurable: true,
      value: 267,
    });
    document.documentElement.style.overflow = "clip";
    document.documentElement.style.overscrollBehavior = "contain";
    document.documentElement.style.scrollBehavior = "smooth";
    document.documentElement.style.height = "83%";
    document.body.style.overflow = "auto";
    document.body.style.position = "relative";
    document.body.style.top = "3px";
    document.body.style.left = "4px";
    document.body.style.width = "95%";
    document.body.style.height = "87%";
    document.body.style.overscrollBehavior = "auto";

    const view = render(
      <ProcessingGateModal
        isOpen
        stage="auth"
        initialScrollPosition={initialScrollPosition}
        cost={25}
        balance={null}
        isBalanceLoading={false}
        error=""
        onClose={onClose}
        onAuthenticated={onAuthenticated}
        onConfirm={onConfirm}
      />,
    );

    expect(document.documentElement.style.overflow).toBe("hidden");
    expect(document.documentElement.style.overscrollBehavior).toBe("none");
    expect(document.documentElement.style.height).toBe("100%");
    expect(document.body.style.overflow).toBe("hidden");
    expect(document.body.style.position).toBe("fixed");
    expect(document.body.style.top).toBe("-240px");
    expect(document.body.style.left).toBe("-17px");
    expect(document.body.style.width).toBe("100%");
    expect(document.body.style.height).toBe("100%");
    expect(document.body.style.overscrollBehavior).toBe("none");

    view.rerender(
      <ProcessingGateModal
        isOpen={false}
        stage="auth"
        initialScrollPosition={initialScrollPosition}
        cost={25}
        balance={null}
        isBalanceLoading={false}
        error=""
        onClose={onClose}
        onAuthenticated={onAuthenticated}
        onConfirm={onConfirm}
      />,
    );

    expect(document.documentElement.style.overflow).toBe("clip");
    expect(document.documentElement.style.overscrollBehavior).toBe("contain");
    expect(document.documentElement.style.scrollBehavior).toBe("smooth");
    expect(document.documentElement.style.height).toBe("83%");
    expect(document.body.style.overflow).toBe("auto");
    expect(document.body.style.position).toBe("relative");
    expect(document.body.style.top).toBe("3px");
    expect(document.body.style.left).toBe("4px");
    expect(document.body.style.width).toBe("95%");
    expect(document.body.style.height).toBe("87%");
    expect(document.body.style.overscrollBehavior).toBe("auto");
    expect(scrollTo).toHaveBeenCalledTimes(1);
    expect(scrollTo).toHaveBeenCalledWith(17, 240);
  });

  // REGRESSION: moving from authentication to cost used to tear down and
  // recreate the lock, which jumped the background while the modal stayed open.
  it("keeps one continuous scroll lock across auth and cost stages", () => {
    Object.defineProperty(window, "scrollY", {
      configurable: true,
      value: 180,
    });
    const view = render(
      <ProcessingGateModal
        isOpen
        stage="auth"
        cost={25}
        balance={null}
        isBalanceLoading={false}
        error=""
        onClose={onClose}
        onAuthenticated={onAuthenticated}
        onConfirm={onConfirm}
      />,
    );

    view.rerender(
      <ProcessingGateModal
        isOpen
        stage="cost"
        cost={25}
        balance={100}
        isBalanceLoading={false}
        error=""
        onClose={onClose}
        onAuthenticated={onAuthenticated}
        onConfirm={onConfirm}
      />,
    );

    expect(document.body.style.position).toBe("fixed");
    expect(document.body.style.top).toBe("-180px");
    expect(scrollTo).not.toHaveBeenCalled();
  });

  // REGRESSION: WebKit can move the root scrolling element while bringing a
  // focused or clicked modal control into view, offsetting pointer hit tests.
  it("clamps an unexpected root scroll while the fixed-body lock is active", () => {
    let scrollX = 11;
    let scrollY = 180;
    Object.defineProperty(window, "scrollX", {
      configurable: true,
      get: () => scrollX,
    });
    Object.defineProperty(window, "scrollY", {
      configurable: true,
      get: () => scrollY,
    });
    scrollTo.mockImplementation((nextX: number, nextY: number) => {
      scrollX = nextX;
      scrollY = nextY;
    });

    render(
      <ProcessingGateModal
        isOpen
        stage="auth"
        cost={25}
        balance={null}
        isBalanceLoading={false}
        error=""
        onClose={onClose}
        onAuthenticated={onAuthenticated}
        onConfirm={onConfirm}
      />,
    );

    scrollX = 29;
    scrollY = 241;
    fireEvent.scroll(window);

    expect(scrollTo).toHaveBeenCalledTimes(1);
    expect(scrollTo).toHaveBeenCalledWith(11, 180);
    expect(window.scrollX).toBe(11);
    expect(window.scrollY).toBe(180);
  });

  // REGRESSION: focusing the email input without preventScroll could move
  // WebKit's root scroller after the body had already been fixed.
  it("autofocuses the email field without scrolling the locked document", () => {
    const focus = jest.spyOn(HTMLInputElement.prototype, "focus");

    render(
      <ProcessingGateModal
        isOpen
        stage="auth"
        cost={25}
        balance={null}
        isBalanceLoading={false}
        error=""
        onClose={onClose}
        onAuthenticated={onAuthenticated}
        onConfirm={onConfirm}
      />,
    );

    expect(focus).toHaveBeenCalledWith({ preventScroll: true });
    focus.mockRestore();
  });

  it("contains scrolling inside a viewport-bounded modal surface", () => {
    render(
      <ProcessingGateModal
        isOpen
        stage="auth"
        cost={25}
        balance={null}
        isBalanceLoading={false}
        error=""
        onClose={onClose}
        onAuthenticated={onAuthenticated}
        onConfirm={onConfirm}
      />,
    );

    expect(screen.getByTestId("processing-gate")).toHaveClass(
      "overflow-y-auto",
      "overscroll-contain",
    );
    expect(screen.getByTestId("processing-gate-card")).toHaveClass(
      "max-h-full",
      "overflow-x-hidden",
      "overflow-y-auto",
      "overscroll-contain",
    );
  });

  it("authenticates inline without navigating away from the selected video", async () => {
    render(
      <ProcessingGateModal
        isOpen
        stage="auth"
        cost={25}
        balance={null}
        isBalanceLoading={false}
        error=""
        onClose={onClose}
        onAuthenticated={onAuthenticated}
        onConfirm={onConfirm}
      />,
    );

    fireEvent.change(screen.getByLabelText("loginEmailLabel"), {
      target: { value: "creator@example.com" },
    });
    fireEvent.change(screen.getByLabelText("loginPasswordLabel"), {
      target: { value: "correct-password" },
    });
    const loginButton = screen.getByRole("button", {
      name: "processingGateLoginSubmit",
    });
    expect(
      screen.queryByRole("link", { name: "registerLegalTermsLink" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "registerLegalPrivacyLink" }),
    ).not.toBeInTheDocument();
    expect(loginButton).not.toHaveAttribute("aria-describedby");
    fireEvent.click(loginButton);

    await waitFor(() => {
      expect(login).toHaveBeenCalledWith(
        "creator@example.com",
        "correct-password",
      );
      expect(onAuthenticated).toHaveBeenCalledTimes(1);
    });
    expect(onConfirm).not.toHaveBeenCalled();
  });

  // REGRESSION: a completed email login from a modal that had already closed
  // could mutate the stale upload flow and reopen its cost confirmation.
  it("does not continue an in-flight email login after the gate closes", async () => {
    let resolveLogin: (() => void) | undefined;
    login.mockReturnValue(
      new Promise<void>((resolve) => {
        resolveLogin = resolve;
      }),
    );
    const view = render(
      <ProcessingGateModal
        isOpen
        stage="auth"
        cost={25}
        balance={null}
        isBalanceLoading={false}
        error=""
        onClose={onClose}
        onAuthenticated={onAuthenticated}
        onConfirm={onConfirm}
      />,
    );
    fireEvent.change(screen.getByLabelText("loginEmailLabel"), {
      target: { value: "creator@example.com" },
    });
    fireEvent.change(screen.getByLabelText("loginPasswordLabel"), {
      target: { value: "correct-password" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "processingGateLoginSubmit" }),
    );
    await waitFor(() => expect(login).toHaveBeenCalledTimes(1));

    view.rerender(
      <ProcessingGateModal
        isOpen={false}
        stage="auth"
        cost={25}
        balance={null}
        isBalanceLoading={false}
        error=""
        onClose={onClose}
        onAuthenticated={onAuthenticated}
        onConfirm={onConfirm}
      />,
    );
    await act(async () => {
      resolveLogin?.();
      await Promise.resolve();
    });

    expect(onAuthenticated).not.toHaveBeenCalled();
  });

  // REGRESSION: Google existed only on /login, forcing guests to abandon the
  // selected upload before they could authenticate with the same provider.
  it("authenticates with Google once and keeps one nonce across auth-mode toggles", async () => {
    render(
      <ProcessingGateModal
        isOpen
        stage="auth"
        cost={25}
        balance={null}
        isBalanceLoading={false}
        error=""
        onClose={onClose}
        onAuthenticated={onAuthenticated}
        onConfirm={onConfirm}
      />,
    );

    await waitFor(() => expect(googleCallback).toBeDefined());
    expect(screen.getByText("official-google-button")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "processingGateCreateAccount" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "processingGateUseLogin" }),
    );
    expect(api.getGoogleAuthNonce).toHaveBeenCalledTimes(1);

    await act(async () => {
      googleCallback?.({ credential: "signed-modal-google-token" });
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(googleLogin).toHaveBeenCalledWith("signed-modal-google-token");
      expect(googleLogin).toHaveBeenCalledTimes(1);
      expect(onAuthenticated).toHaveBeenCalledTimes(1);
    });
    expect(login).not.toHaveBeenCalled();
    expect(register).not.toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("refreshes an expired Google nonce inline without clearing typed form state", async () => {
    (api.getGoogleAuthNonce as jest.Mock)
      .mockResolvedValueOnce({
        nonce: "stale-modal-nonce",
        expires_in: 600,
        client_id: "google-client-id",
      })
      .mockResolvedValueOnce({
        nonce: "fresh-modal-nonce",
        expires_in: 600,
        client_id: "google-client-id",
      });
    googleLogin.mockRejectedValueOnce(
      new Error("Google login nonce could not be verified."),
    );
    render(
      <ProcessingGateModal
        isOpen
        stage="auth"
        cost={25}
        balance={null}
        isBalanceLoading={false}
        error=""
        onClose={onClose}
        onAuthenticated={onAuthenticated}
        onConfirm={onConfirm}
      />,
    );

    const emailInput = screen.getByLabelText("loginEmailLabel");
    fireEvent.change(emailInput, { target: { value: "kept@example.com" } });
    await waitFor(() => expect(googleCallback).toBeDefined());
    await act(async () => {
      googleCallback?.({ credential: "stale-modal-google-token" });
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(
        "loginGoogleExpired",
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "loginGoogleReload" }));

    await waitFor(() => {
      expect(api.getGoogleAuthNonce).toHaveBeenCalledTimes(2);
      expect(window.google?.accounts?.id?.initialize).toHaveBeenLastCalledWith(
        expect.objectContaining({ nonce: "fresh-modal-nonce" }),
      );
    });
    expect(reloadGoogleIdentityPage).not.toHaveBeenCalled();
    expect(emailInput).toHaveValue("kept@example.com");
    expect(onAuthenticated).not.toHaveBeenCalled();
  });

  // REGRESSION: legal navigation replaced the upload workspace and lost the
  // guest's selected video and inline registration state.
  it("supports account creation inside the same gate", async () => {
    render(
      <ProcessingGateModal
        isOpen
        stage="auth"
        cost={25}
        balance={null}
        isBalanceLoading={false}
        error=""
        onClose={onClose}
        onAuthenticated={onAuthenticated}
        onConfirm={onConfirm}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "processingGateCreateAccount" }),
    );
    const legalNotice = document.getElementById(
      "processing-gate-register-legal-notice",
    );
    expect(legalNotice).toBeInTheDocument();
    expect(legalNotice).toHaveTextContent("registerLegalIntro");
    expect(legalNotice).toHaveTextContent("registerLegalConnector");
    const termsLink = screen.getByRole("link", {
      name: "registerLegalTermsLink",
    });
    const privacyLink = screen.getByRole("link", {
      name: "registerLegalPrivacyLink",
    });
    expect(termsLink).toHaveAttribute("href", "/terms");
    expect(termsLink).toHaveAttribute("target", "_blank");
    expect(termsLink).toHaveAttribute("rel", "noopener noreferrer");
    expect(privacyLink).toHaveAttribute("href", "/privacy");
    expect(privacyLink).toHaveAttribute("target", "_blank");
    expect(privacyLink).toHaveAttribute("rel", "noopener noreferrer");

    fireEvent.change(screen.getByLabelText("registerNameLabel"), {
      target: { value: "Creator" },
    });
    fireEvent.change(screen.getByLabelText("loginEmailLabel"), {
      target: { value: "new@example.com" },
    });
    fireEvent.change(screen.getByLabelText("loginPasswordLabel"), {
      target: { value: "twelve-chars!" },
    });
    const registerButton = screen.getByRole("button", {
      name: "processingGateRegisterSubmit",
    });
    expect(registerButton).toHaveAttribute(
      "aria-describedby",
      "processing-gate-register-legal-notice",
    );
    expect(legalNotice?.nextElementSibling).toBe(registerButton);
    fireEvent.click(registerButton);

    await waitFor(() => {
      expect(register).toHaveBeenCalledWith(
        "new@example.com",
        "twelve-chars!",
        "Creator",
      );
      expect(onAuthenticated).toHaveBeenCalledTimes(1);
    });
  });

  it("does not steal focus back from the password field after initial autofocus", () => {
    jest.useFakeTimers();
    render(
      <ProcessingGateModal
        isOpen
        stage="auth"
        cost={50}
        balance={null}
        isBalanceLoading={false}
        error=""
        onClose={onClose}
        onAuthenticated={onAuthenticated}
        onConfirm={onConfirm}
      />,
    );

    const emailInput = screen.getByLabelText("loginEmailLabel");
    const passwordInput = screen.getByLabelText("loginPasswordLabel");
    expect(emailInput).toHaveFocus();

    fireEvent.change(emailInput, { target: { value: "guest@example.com" } });
    passwordInput.focus();
    act(() => jest.advanceTimersByTime(100));

    expect(passwordInput).toHaveFocus();
    fireEvent.change(passwordInput, {
      target: { value: "correct horse battery staple" },
    });
    expect(emailInput).toHaveValue("guest@example.com");
    expect(passwordInput).toHaveValue("correct horse battery staple");
  });
});
