"use client";

import { useCallback, useRef, useState } from "react";
import type { User } from "@/context/AuthContext";
import type { MessageKey } from "@/context/i18nMessages";
import { api } from "@/lib/api";

type Translate = (
  key: MessageKey,
  params?: Record<string, string | number>,
) => string;

export function useDashboardAccount({
  user,
  logout,
  refreshUser,
  t,
}: {
  user: User | null;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  t: Translate;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<"profile" | "history">("profile");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  const close = useCallback(() => setIsOpen(false), []);
  const openProfile = useCallback(() => {
    setActiveTab("profile");
    setIsOpen(true);
  }, []);
  const logoutFromAccount = useCallback(async () => {
    setError("");
    try {
      await logout();
      setIsOpen(false);
    } catch {
      setError(t("signOutError"));
    }
  }, [logout, t]);

  const saveProfile = useCallback(
    async (name: string, password?: string, confirmPassword?: string) => {
      if (!user) return;
      setError("");
      setMessage("");
      setIsSaving(true);
      try {
        if (name && name !== user.name) {
          await api.updateProfile(name);
          await refreshUser();
          setMessage(t("profileUpdated"));
        }
        if (user.provider === "local" && (password || confirmPassword)) {
          if (password !== confirmPassword) {
            setError(t("passwordsMismatch"));
            return;
          }
          await api.updatePassword(password!, confirmPassword!);
          setMessage(t("passwordUpdated"));
        }
      } catch (saveError) {
        setError(
          saveError instanceof Error
            ? saveError.message
            : t("accountUpdateError"),
        );
      } finally {
        setIsSaving(false);
      }
    },
    [refreshUser, t, user],
  );

  const showPreview = useCallback((show: boolean) => {
    if (!show) return;
    setIsOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  return {
    isOpen,
    activeTab,
    message,
    error,
    isSaving,
    returnFocusRef,
    close,
    openProfile,
    setActiveTab,
    logoutFromAccount,
    saveProfile,
    showPreview,
  };
}
