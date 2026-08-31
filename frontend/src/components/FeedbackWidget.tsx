"use client";

import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { useAuth } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import type { MessageKey } from "@/context/i18nMessages";
import { useDocumentScrollLock } from "@/hooks/useDocumentScrollLock";
import {
  api,
  type ProductFeedbackCategory,
  type ProductFeedbackPayload,
} from "@/lib/api";
import { reportProductAction } from "@/lib/observability";

const MIN_MESSAGE_CHARS = 10;
const MAX_MESSAGE_CHARS = 2_000;
const MIN_FORM_AGE_MS = 2_000;
const FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "a[href]",
  'input:not([disabled]):not([tabindex="-1"])',
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

interface FeedbackFormValues {
  category: ProductFeedbackCategory;
  message: string;
  website: string;
}

interface FeedbackWidgetProps {
  initiallyOpen?: boolean;
}

const categories: ReadonlyArray<{
  value: ProductFeedbackCategory;
  label: MessageKey;
  icon: string;
}> = [
  { value: "idea", label: "feedbackCategoryIdea", icon: "✦" },
  { value: "bug", label: "feedbackCategoryBug", icon: "!" },
  { value: "complaint", label: "feedbackCategoryComplaint", icon: "–" },
  { value: "chat", label: "feedbackCategoryChat", icon: "…" },
];

function handleFeedbackDialogKeyDown(
  event: KeyboardEvent,
  dialog: HTMLElement | null,
  close: () => void,
): void {
  if (event.key === "Escape") {
    event.preventDefault();
    close();
    return;
  }
  if (event.key !== "Tab" || !dialog) return;

  const focusable = Array.from(
    dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
  ).filter((element) => element.getClientRects().length > 0);
  if (focusable.length === 0) {
    event.preventDefault();
    dialog.focus();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const active = document.activeElement;
  if (event.shiftKey && (active === first || !dialog.contains(active))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && active === last) {
    event.preventDefault();
    first.focus();
  }
}

function feedbackSubmitLabel(
  isSubmitting: boolean,
  canSubmit: boolean,
  t: ReturnType<typeof useI18n>["t"],
): string {
  if (isSubmitting) return t("feedbackSubmitting");
  if (!canSubmit) return t("feedbackWaitMoment");
  return t("feedbackSubmit");
}

export function FeedbackWidget({ initiallyOpen = false }: FeedbackWidgetProps) {
  const { t } = useI18n();
  const { user } = useAuth();
  const descriptionId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [isOpen, setIsOpen] = useState(initiallyOpen);
  const [formStartedAt, setFormStartedAt] = useState(() =>
    initiallyOpen ? Math.floor(Date.now() / 1_000) : 0,
  );
  const [canSubmit, setCanSubmit] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [requestError, setRequestError] = useState(false);
  const {
    register,
    handleSubmit,
    reset,
    setValue,
    control,
    formState: { errors, isSubmitting },
  } = useForm<FeedbackFormValues>({
    defaultValues: {
      category: "idea",
      message: "",
      website: "",
    },
  });
  const selectedCategory = useWatch({ control, name: "category" });
  const message = useWatch({ control, name: "message" });
  const trimmedMessageLength = message.trim().length;
  const messageIsTooShort =
    trimmedMessageLength > 0 && trimmedMessageLength < MIN_MESSAGE_CHARS;
  const messageRegistration = register("message", {
    required: t("feedbackMessageRequired"),
    minLength: {
      value: MIN_MESSAGE_CHARS,
      message: t("feedbackMessageTooShort"),
    },
    maxLength: {
      value: MAX_MESSAGE_CHARS,
      message: t("feedbackMessageTooLong"),
    },
  });

  useDocumentScrollLock(isOpen);

  const close = useCallback(() => {
    setIsOpen(false);
  }, []);

  const open = useCallback(() => {
    reset({ category: "idea", message: "", website: "" });
    setSubmitted(false);
    setRequestError(false);
    setCanSubmit(false);
    setFormStartedAt(Math.floor(Date.now() / 1_000));
    setIsOpen(true);
    reportProductAction("feedback_opened");
  }, [reset]);

  useEffect(() => {
    if (!isOpen) return;

    const returnFocus = triggerRef.current;
    const focusTimer = window.setTimeout(() => {
      if (window.navigator.maxTouchPoints > 0) {
        dialogRef.current?.focus({ preventScroll: true });
        return;
      }
      textareaRef.current?.focus({ preventScroll: true });
    }, 80);
    const safetyTimer = window.setTimeout(
      () => setCanSubmit(true),
      MIN_FORM_AGE_MS,
    );
    const handleKeyDown = (event: KeyboardEvent) =>
      handleFeedbackDialogKeyDown(event, dialogRef.current, close);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      window.clearTimeout(safetyTimer);
      document.removeEventListener("keydown", handleKeyDown);
      returnFocus?.focus();
    };
  }, [close, isOpen]);

  const submit = handleSubmit(async (values) => {
    setRequestError(false);
    const payload: ProductFeedbackPayload = {
      category: values.category,
      message: values.message.trim(),
      source_path: window.location.pathname || "/",
      page_title: document.title.slice(0, 512) || "GSUBS",
      form_started_at: formStartedAt,
      website: values.website,
    };
    try {
      await api.createProductFeedback(payload);
      reportProductAction("feedback_submitted", { outcome: "succeeded" });
      setSubmitted(true);
      reset({ category: values.category, message: "", website: "" });
    } catch {
      reportProductAction("feedback_failed", { outcome: "failed" });
      setRequestError(true);
    }
  });

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        aria-label={t("feedbackOpen")}
        aria-expanded={isOpen}
        aria-controls="gsubs-feedback-dialog"
        onClick={open}
        data-testid="feedback-trigger"
        className="fixed bottom-[calc(env(safe-area-inset-bottom)_+_1rem)] right-[calc(env(safe-area-inset-right)_+_1rem)] z-40 inline-flex min-h-12 items-center gap-2 rounded-full border border-[#d7d9de] bg-white px-3.5 py-2.5 text-sm font-bold text-[#24272d] shadow-[0_12px_32px_rgb(20_24_32/0.16)] transition duration-150 hover:-translate-y-0.5 hover:border-[#b9bdc5] hover:shadow-[0_16px_38px_rgb(20_24_32/0.2)] sm:px-4"
      >
        <svg
          className="h-5 w-5 text-[var(--accent)]"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.9"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M7.5 18.5 4 20l1.15-3.8A8 8 0 1 1 7.5 18.5Z"
          />
          <path strokeLinecap="round" d="M8.5 9.5h7M8.5 13h4.5" />
        </svg>
        <span className="hidden sm:inline">{t("feedbackOpenShort")}</span>
      </button>

      {isOpen && (
        <div
          className="fixed inset-0 z-[60] flex cursor-pointer items-end justify-end bg-black/25 p-0 backdrop-blur-[2px] sm:p-[max(1rem,env(safe-area-inset-right))]"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) close();
          }}
        >
          <section
            ref={dialogRef}
            id="gsubs-feedback-dialog"
            role="dialog"
            tabIndex={-1}
            aria-modal="true"
            aria-label={t("feedbackTitle")}
            aria-describedby={descriptionId}
            data-testid="feedback-dialog"
            className="relative max-h-[calc(100dvh-env(safe-area-inset-top)-0.75rem)] w-full touch-pan-y cursor-default overflow-y-auto overscroll-y-contain rounded-t-[22px] border border-[#d9dbe0] bg-white shadow-[0_24px_80px_rgb(17_24_39/0.24)] [-webkit-overflow-scrolling:touch] sm:max-h-[min(720px,calc(100dvh-2rem))] sm:w-[390px] sm:rounded-[20px]"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="h-1 w-full rounded-t-[inherit] bg-[var(--accent)]" />
            <div className="p-5 pb-[calc(env(safe-area-inset-bottom)_+_1.25rem)] sm:p-6">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-[11px] font-extrabold uppercase tracking-[0.16em] text-[var(--accent)]">
                    {t("feedbackKicker")}
                  </p>
                  <h2 className="mt-1 text-xl font-extrabold tracking-[-0.025em] text-[#111215]">
                    {t("feedbackTitle")}
                  </h2>
                </div>
                <button
                  type="button"
                  aria-label={t("feedbackClose")}
                  onClick={close}
                  className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-[#e0e2e6] text-[#6f747d] transition hover:bg-[#f4f5f6] hover:text-[#111215]"
                >
                  <svg
                    className="h-5 w-5"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    aria-hidden="true"
                  >
                    <path strokeLinecap="round" d="m7 7 10 10M17 7 7 17" />
                  </svg>
                </button>
              </div>

              <p
                id={descriptionId}
                className="mt-2 text-sm leading-6 text-[#6d7179]"
              >
                {t("feedbackDescription")}
              </p>

              {submitted ? (
                <div className="mt-6 rounded-2xl border border-emerald-200 bg-emerald-50 p-5 text-center">
                  <div
                    className="mx-auto flex h-11 w-11 items-center justify-center rounded-full bg-emerald-600 text-white"
                    aria-hidden="true"
                  >
                    ✓
                  </div>
                  <p role="status" className="mt-3 font-bold text-emerald-950">
                    {t("feedbackSuccess")}
                  </p>
                  <p className="mt-1 text-sm leading-6 text-emerald-800">
                    {t("feedbackSuccessDetail")}
                  </p>
                  <div className="mt-4 grid grid-cols-2 gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        setSubmitted(false);
                        setCanSubmit(false);
                        setFormStartedAt(Math.floor(Date.now() / 1_000));
                        window.setTimeout(
                          () => setCanSubmit(true),
                          MIN_FORM_AGE_MS,
                        );
                      }}
                      className="min-h-11 rounded-xl border border-emerald-300 bg-white px-3 text-sm font-bold text-emerald-900"
                    >
                      {t("feedbackSendAnother")}
                    </button>
                    <button
                      type="button"
                      onClick={close}
                      className="min-h-11 rounded-xl bg-emerald-700 px-3 text-sm font-bold text-white"
                    >
                      {t("feedbackDone")}
                    </button>
                  </div>
                </div>
              ) : (
                <form className="mt-5" onSubmit={submit} noValidate>
                  <fieldset>
                    <legend className="text-xs font-bold uppercase tracking-[0.08em] text-[#6d7179]">
                      {t("feedbackCategoryLabel")}
                    </legend>
                    <div
                      className="mt-2 grid grid-cols-2 gap-2"
                      role="radiogroup"
                    >
                      {categories.map((category) => {
                        const selected = selectedCategory === category.value;
                        return (
                          <label
                            key={category.value}
                            className={`relative flex min-h-11 cursor-pointer items-center gap-2 rounded-xl border px-3 text-sm font-bold transition ${
                              selected
                                ? "border-[var(--accent)] bg-blue-50 text-[#075be4] shadow-[inset_0_0_0_1px_rgb(18_103_244/0.08)]"
                                : "border-[#dedfe3] bg-white text-[#555a63] hover:bg-[#f7f7f5]"
                            }`}
                          >
                            <input
                              type="radio"
                              value={category.value}
                              className="absolute inset-0 z-10 h-full w-full cursor-pointer rounded-xl opacity-0 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
                              {...register("category")}
                              onChange={() =>
                                setValue("category", category.value, {
                                  shouldDirty: true,
                                })
                              }
                            />
                            <span
                              className={`flex h-6 w-6 items-center justify-center rounded-full text-xs ${
                                selected
                                  ? "bg-[var(--accent)] text-white"
                                  : "bg-[#eef0f3] text-[#6d7179]"
                              }`}
                              aria-hidden="true"
                            >
                              {category.icon}
                            </span>
                            {t(category.label)}
                          </label>
                        );
                      })}
                    </div>
                  </fieldset>

                  <label
                    htmlFor="feedback-message"
                    className="mt-5 block text-sm font-bold text-[#343840]"
                  >
                    {t("feedbackMessageLabel")}
                  </label>
                  <textarea
                    id="feedback-message"
                    rows={5}
                    maxLength={MAX_MESSAGE_CHARS}
                    placeholder={t("feedbackMessagePlaceholder")}
                    aria-invalid={Boolean(errors.message) || messageIsTooShort}
                    aria-describedby={
                      errors.message || messageIsTooShort
                        ? "feedback-message-error"
                        : "feedback-message-help"
                    }
                    className="mt-2 min-h-32 w-full resize-y rounded-xl border border-[#d7d9de] bg-white px-3.5 py-3 text-base leading-6 text-[#111215] outline-none transition placeholder:text-[#a1a4aa] focus:border-[var(--accent)] focus:ring-4 focus:ring-blue-100"
                    {...messageRegistration}
                    ref={(element) => {
                      messageRegistration.ref(element);
                      textareaRef.current = element;
                    }}
                  />
                  <div className="mt-1.5 flex items-start justify-between gap-3 text-xs">
                    <p
                      id={
                        errors.message || messageIsTooShort
                          ? "feedback-message-error"
                          : "feedback-message-help"
                      }
                      className={
                        errors.message || messageIsTooShort
                          ? "font-semibold text-[var(--danger)]"
                          : "text-[#858991]"
                      }
                    >
                      {errors.message?.message ??
                        (messageIsTooShort
                          ? t("feedbackMessageTooShort")
                          : t("feedbackMessageHelp"))}
                    </p>
                    <span className="shrink-0 tabular-nums text-[#858991]">
                      {message.length}/{MAX_MESSAGE_CHARS}
                    </span>
                  </div>

                  <div
                    className="absolute -left-[9999px] h-px w-px overflow-hidden"
                    aria-hidden="true"
                  >
                    <label htmlFor="feedback-website">Website</label>
                    <input
                      id="feedback-website"
                      type="text"
                      tabIndex={-1}
                      autoComplete="off"
                      {...register("website")}
                    />
                  </div>

                  <p className="mt-4 rounded-xl bg-[#f5f6f8] px-3 py-2.5 text-xs leading-5 text-[#666b74]">
                    {user
                      ? t("feedbackSignedInNotice", { email: user.email })
                      : t("feedbackAnonymousNotice")}{" "}
                    <Link
                      href="/privacy"
                      className="font-bold text-[var(--accent)] underline underline-offset-2"
                    >
                      {t("feedbackPrivacyLink")}
                    </Link>
                  </p>

                  {requestError && (
                    <p
                      role="alert"
                      className="mt-3 text-sm font-semibold text-[var(--danger)]"
                    >
                      {t("feedbackError")}
                    </p>
                  )}

                  <button
                    type="submit"
                    disabled={
                      isSubmitting || !canSubmit || trimmedMessageLength === 0
                    }
                    className="mt-4 inline-flex min-h-12 w-full items-center justify-center rounded-xl bg-[var(--accent)] px-4 font-bold text-white shadow-[0_9px_22px_rgb(18_103_244/0.2)] transition hover:bg-[#075be4] disabled:cursor-not-allowed disabled:bg-[#aeb8c8] disabled:shadow-none"
                  >
                    {feedbackSubmitLabel(isSubmitting, canSubmit, t)}
                  </button>
                </form>
              )}
            </div>
          </section>
        </div>
      )}
    </>
  );
}
