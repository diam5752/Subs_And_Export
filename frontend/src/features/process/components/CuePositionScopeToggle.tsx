import React, { memo } from "react";
import type { SubtitlePositionScope } from "@/components/SubtitleOverlay";
import { useI18n } from "@/context/I18nContext";

interface CuePositionScopeToggleProps {
  scope: SubtitlePositionScope;
  disabled: boolean;
  onScopeChange: (scope: SubtitlePositionScope) => void;
}

export const CuePositionScopeToggle = memo(
  ({ scope, disabled, onScopeChange }: CuePositionScopeToggleProps) => {
    const { t } = useI18n();
    const hintId = React.useId();
    const currentCueOnly = scope === "cue";
    return (
      <div
        className="subtitle-position-scope-control"
        data-scope={scope}
        data-testid="subtitle-position-scope"
      >
        <span className="subtitle-position-scope-label">
          {t("subtitlePositionScopeLabel")}
        </span>
        <button
          type="button"
          role="switch"
          aria-checked={currentCueOnly}
          aria-describedby={hintId}
          aria-label={t("subtitlePositionScopeLabel")}
          disabled={disabled}
          onClick={() => onScopeChange(currentCueOnly ? "all" : "cue")}
          className="subtitle-position-scope-toggle"
        >
          <span aria-hidden="true" className="subtitle-position-scope-switch" />
          <span aria-hidden="true" className="subtitle-position-scope-state">
            {t(
              currentCueOnly
                ? "subtitlePositionScopeOn"
                : "subtitlePositionScopeOff",
            )}
          </span>
        </button>
        <p id={hintId} className="subtitle-position-scope-hint">
          {t(
            currentCueOnly
              ? "subtitleDragHandleLabel"
              : "subtitleDragAllHandleLabel",
          )}
        </p>
      </div>
    );
  },
);
CuePositionScopeToggle.displayName = "CuePositionScopeToggle";
