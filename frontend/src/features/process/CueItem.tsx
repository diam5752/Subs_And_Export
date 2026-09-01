import React, { memo, useRef, useEffect } from "react";
import { Cue, type SubtitlePositionScope } from "@/components/SubtitleOverlay";
import { useI18n } from "@/context/I18nContext";
import { CueEditor } from "./components/CueEditor";
import { CueItemReadActions } from "./components/CueItemReadActions";
import { CuePositionScopeToggle } from "./components/CuePositionScopeToggle";

interface CueItemProps {
  cue: Cue;
  index: number;
  isActive: boolean;
  isEditing: boolean;
  canEdit: boolean;
  draftText: string;
  isSaving: boolean;
  onSeek: (time: number) => void;
  onEdit: (index: number) => void;
  onSave: () => void;
  onCancel: () => void;
  onUpdateDraft: (text: string) => void;
  autoFocusEditor?: boolean;
  onResetPosition?: (index: number) => void;
  positionScope?: SubtitlePositionScope;
  positionScopeDisabled?: boolean;
  onPositionScopeChange?: (scope: SubtitlePositionScope) => void;
}

type Translate = ReturnType<typeof useI18n>["t"];

function CueTimeButton({
  start,
  formattedTime,
  t,
  onSeek,
}: {
  start: number;
  formattedTime: string;
  t: Translate;
  onSeek: (time: number) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSeek(start)}
      className="cue-time-button font-mono text-xs opacity-60 pt-0.5 min-w-[42px] text-left hover:opacity-90 transition-opacity focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:outline-none rounded-sm"
      aria-label={
        t("jumpToTime")?.replace("{time}", formattedTime) ||
        `Jump to ${formattedTime}`
      }
    >
      {formattedTime}
    </button>
  );
}

export const CueItem = memo(
  ({
    cue,
    index,
    isActive,
    isEditing,
    canEdit,
    draftText,
    isSaving,
    onSeek,
    onEdit,
    onSave,
    onCancel,
    onUpdateDraft,
    autoFocusEditor = true,
    onResetPosition,
    positionScope,
    positionScopeDisabled = false,
    onPositionScopeChange,
  }: CueItemProps) => {
    const { t } = useI18n();
    const formattedTime = `${Math.floor(cue.start / 60)}:${(cue.start % 60).toFixed(0).padStart(2, "0")}`;

    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const editBtnRef = useRef<HTMLButtonElement>(null);
    const prevIsEditingRef = useRef(isEditing);
    const shouldRestoreFocusRef = useRef(false);

    useEffect(() => {
      // Entering edit mode
      if (isEditing && !prevIsEditingRef.current && autoFocusEditor) {
        requestAnimationFrame(() => {
          textareaRef.current?.focus();
        });
      }

      // Exiting edit mode
      if (!isEditing && prevIsEditingRef.current) {
        if (shouldRestoreFocusRef.current) {
          requestAnimationFrame(() => {
            editBtnRef.current?.focus();
          });
          shouldRestoreFocusRef.current = false;
        }
      }

      prevIsEditingRef.current = isEditing;
    }, [autoFocusEditor, isEditing]);

    const handleSave = () => {
      shouldRestoreFocusRef.current = true;
      onSave();
    };

    const handleCancel = () => {
      shouldRestoreFocusRef.current = true;
      onCancel();
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        handleSave();
      } else if (e.key === "Escape") {
        e.preventDefault();
        handleCancel();
      }
    };

    return (
      <div
        id={`cue-${index}`}
        className={`cue-item rounded-lg border px-2 py-2 transition-colors ${
          isActive
            ? "border-[var(--accent)]/25 bg-[var(--accent)]/10"
            : "border-transparent hover:bg-white/5"
        }`}
        data-active={isActive}
      >
        <div className="flex items-start gap-3">
          <CueTimeButton
            start={cue.start}
            formattedTime={formattedTime}
            t={t}
            onSeek={onSeek}
          />
          <div className="flex-1 min-w-0">
            {isActive && positionScope && onPositionScopeChange && (
              <CuePositionScopeToggle
                scope={positionScope}
                disabled={positionScopeDisabled}
                onScopeChange={onPositionScopeChange}
              />
            )}
            {isEditing ? (
              <CueEditor
                textareaRef={textareaRef}
                draftText={draftText}
                isSaving={isSaving}
                t={t}
                onUpdateDraft={onUpdateDraft}
                onKeyDown={handleKeyDown}
                onSave={handleSave}
                onCancel={handleCancel}
              />
            ) : (
              <button
                type="button"
                onClick={() => onSeek(cue.start)}
                className={`cue-text-button w-full text-left text-sm break-words [overflow-wrap:anywhere] rounded-sm focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:outline-none p-0.5 -m-0.5 transition-colors ${
                  isActive
                    ? "text-[var(--foreground)] font-medium"
                    : "text-[var(--muted)] hover:text-[var(--foreground)]"
                }`}
                aria-label={
                  t("jumpToCue")?.replace("{text}", cue.text) ||
                  `Jump to cue: ${cue.text}`
                }
              >
                {cue.text}
              </button>
            )}
          </div>
          {!isEditing && (
            <CueItemReadActions
              cue={cue}
              index={index}
              canEdit={canEdit}
              formattedTime={formattedTime}
              editButtonRef={editBtnRef}
              onEdit={onEdit}
              onResetPosition={onResetPosition}
            />
          )}
        </div>
      </div>
    );
  },
);

CueItem.displayName = "CueItem";
