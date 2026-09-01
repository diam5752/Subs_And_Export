import React, { memo, useCallback, useEffect, useMemo, useRef } from "react";
import dynamic from "next/dynamic";
import { useI18n } from "@/context/I18nContext";
import { useProcessContext } from "../ProcessContext";
import { TranscriptPanel } from "./SidebarTranscript";

const SubtitlePositionSelector = dynamic(() =>
  import("@/components/SubtitlePositionSelector").then(
    (module) => module.SubtitlePositionSelector,
  ),
);

interface SidebarTabsProps {
  activeTab: "transcript" | "styles";
  onChange: (tab: "transcript" | "styles") => void;
  transcriptLabel: string;
  captionsLabel: string;
  stylesLabel: string;
}

const SidebarTabs = memo((props: SidebarTabsProps) => (
  <div className="editor-tabs-sticky">
    <div role="tablist" className="editor-tabs editor-tabs-two">
      <button
        role="tab"
        id="tab-transcript"
        aria-label={props.transcriptLabel}
        aria-selected={props.activeTab === "transcript"}
        aria-controls="panel-transcript"
        onClick={() => props.onChange("transcript")}
        className={`editor-tab ${props.activeTab === "transcript" ? "editor-tab-active" : ""}`}
      >
        <svg
          className="hidden h-4 w-4 shrink-0 sm:block"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
          />
        </svg>
        <span className="editor-tab-label-full truncate">
          {props.transcriptLabel}
        </span>
        <span className="editor-tab-label-short">{props.captionsLabel}</span>
      </button>
      <button
        role="tab"
        id="tab-styles"
        aria-selected={props.activeTab === "styles"}
        aria-controls="panel-styles"
        onClick={() => props.onChange("styles")}
        className={`editor-tab ${props.activeTab === "styles" ? "editor-tab-active" : ""}`}
      >
        <svg
          className="hidden h-4 w-4 shrink-0 sm:block"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01"
          />
        </svg>
        <span className="truncate">{props.stylesLabel}</span>
      </button>
    </div>
  </div>
));
SidebarTabs.displayName = "SidebarTabs";

export function Sidebar() {
  const { t } = useI18n();
  const process = useProcessContext();
  const sidebarBodyRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (sidebarBodyRef.current) sidebarBodyRef.current.scrollTop = 0;
  }, [process.activeSidebarTab]);
  const handleSidebarTabChange = useCallback(
    (tab: "transcript" | "styles") => {
      process.setActiveSidebarTab(tab);
      if (
        tab !== "styles" ||
        !window.matchMedia?.("(max-width: 899px)").matches
      )
        return;
      window.requestAnimationFrame(() => {
        const reduceMotion = window.matchMedia?.(
          "(prefers-reduced-motion: reduce)",
        ).matches;
        document.getElementById("preview-section")?.scrollIntoView?.({
          behavior: reduceMotion ? "auto" : "smooth",
          block: "start",
        });
      });
    },
    [process],
  );
  const stylesPanel = useMemo(
    () => (
      <div
        role="tabpanel"
        id="panel-styles"
        aria-labelledby="tab-styles"
        className="editor-style-panel animate-fade-in pr-2"
        data-testid="editor-style-panel"
      >
        <SubtitlePositionSelector
          lines={process.maxSubtitleLines}
          onChangeLines={process.setMaxSubtitleLines}
          subtitleColor={process.subtitleColor}
          onChangeColor={process.setSubtitleColor}
          colors={process.SUBTITLE_COLORS}
          subtitleSize={process.subtitleSize}
          onChangeSize={process.setSubtitleSize}
        />
      </div>
    ),
    [process],
  );
  if (!process.selectedJob) return null;
  return (
    <aside className="editor-sidebar" data-testid="editor-sidebar">
      <div
        ref={sidebarBodyRef}
        className="editor-sidebar-body custom-scrollbar"
      >
        <SidebarTabs
          activeTab={process.activeSidebarTab}
          onChange={handleSidebarTabChange}
          transcriptLabel={t("tabTranscript") || "Transcript"}
          captionsLabel={t("stepCaptions") || "Captions"}
          stylesLabel={t("tabStyles") || "Styles"}
        />
        <div className="editor-tab-content">
          {process.activeSidebarTab === "transcript" && <TranscriptPanel />}
          {process.activeSidebarTab === "styles" && stylesPanel}
        </div>
      </div>
    </aside>
  );
}
