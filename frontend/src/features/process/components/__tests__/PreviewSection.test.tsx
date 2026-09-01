import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { PreviewSection } from "../PreviewSection";
import { useProcessContext } from "../../ProcessContext";
import { usePlaybackContext } from "../../PlaybackContext";

jest.mock("@/context/I18nContext", () => ({
  useI18n: () => ({ t: (key: string) => key }),
}));

jest.mock("../../ProcessContext", () => ({
  useProcessContext: jest.fn(),
}));

jest.mock("../../PlaybackContext", () => ({
  usePlaybackContext: jest.fn(),
}));

jest.mock("@/components/PhoneFrame", () => ({
  PhoneFrame: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="phone-frame">{children}</div>
  ),
}));

jest.mock("@/components/PreviewPlayer", () => ({
  PreviewPlayer: React.forwardRef(function MockPreviewPlayer(
    {
      videoUrl,
      cues,
      onTimeUpdate,
      subtitleEditor,
      subtitleTransformControls,
    }: {
      videoUrl: string;
      cues: Array<{ text: string }>;
      onTimeUpdate?: (time: number) => void;
      subtitleEditor?: {
        cues: Array<{ text: string }>;
        onBeginEdit: (index: number) => void;
      };
      subtitleTransformControls?: {
        onPositionChange: (cueIndex: number, position: number) => void;
        onCuePositionChange?: (cueIndex: number, position: number) => void;
        onSizeChange: (size: number) => void;
      };
    },
    ref,
  ) {
    React.useImperativeHandle(ref, () => ({
      seekTo: mockSeekTo,
      pause: jest.fn(),
      togglePlayback: jest.fn(),
      toggleMuted: jest.fn(),
    }));
    return (
      <div>
        <button
          type="button"
          data-testid="preview-player"
          onClick={() => onTimeUpdate?.(12.5)}
        >
          {videoUrl}:{cues.length}
        </button>
        <button
          type="button"
          data-testid="cue-position-on-video"
          onClick={() =>
            subtitleTransformControls?.onCuePositionChange?.(0, 43)
          }
        >
          cue-position-on-video
        </button>
        <button
          type="button"
          data-testid="inline-editor-bridge"
          data-source-cues={subtitleEditor?.cues.length ?? 0}
          onClick={() => subtitleEditor?.onBeginEdit(0)}
        >
          edit-on-video
        </button>
        <button
          type="button"
          data-testid="position-on-video"
          onClick={() => subtitleTransformControls?.onPositionChange(0, 42)}
        >
          position-on-video
        </button>
        <button
          type="button"
          data-testid="resize-on-video"
          onClick={() => subtitleTransformControls?.onSizeChange(115)}
        >
          resize-on-video
        </button>
      </div>
    );
  }),
}));

const mockSeekTo = jest.fn();

jest.mock("../Sidebar", () => ({
  Sidebar: () => <div data-testid="sidebar" />,
}));

jest.mock("../NewVideoConfirmModal", () => ({
  NewVideoConfirmModal: ({
    isOpen,
    onClose,
    onConfirm,
  }: {
    isOpen: boolean;
    onClose: () => void;
    onConfirm: () => void;
  }) =>
    isOpen ? (
      <div data-testid="new-video-modal">
        <button type="button" onClick={onConfirm}>
          confirm-new-video
        </button>
        <button type="button" onClick={onClose}>
          close-new-video
        </button>
      </div>
    ) : null,
}));

jest.mock("@/components/VideoModal", () => ({
  VideoModal: ({
    isOpen,
    onClose,
  }: {
    isOpen: boolean;
    onClose: () => void;
  }) =>
    isOpen ? (
      <div data-testid="video-modal">
        <button type="button" onClick={onClose}>
          close-preview
        </button>
      </div>
    ) : null,
}));

function buildContext() {
  return {
    selectedJob: null as {
      status: string;
      result_data?: {
        transcribe_provider?: string;
        transcribe_tier?: string;
        original_filename?: string | null;
      };
    } | null,
    isProcessing: false,
    videoUrl: "blob:video",
    processedCues: [{ start: 0, end: 1, text: "hello" }],
    cues: [{ start: 0, end: 1, text: "hello" }],
    subtitlePosition: 20,
    setSubtitlePosition: jest.fn(),
    changeCuePosition: jest.fn(),
    commitCuePosition: jest.fn(async () => {}),
    cancelCuePosition: jest.fn(),
    resetCuePosition: jest.fn(async () => {}),
    subtitleColor: "#FFFF00",
    subtitleSize: 100,
    setSubtitleSize: jest.fn(),
    karaokeEnabled: true,
    maxSubtitleLines: 2,
    shadowStrength: 4,
    watermarkEnabled: true,
    activeSidebarTab: "transcript" as "transcript" | "styles",
    playerRef: React.createRef(),
    resultsRef: React.createRef<HTMLDivElement>(),
    currentStep: 3,
    setOverrideStep: jest.fn(),
    handleExport: jest.fn(async () => {}),
    exportingResolutions: {},
    exportProgress: {},
    exportError: null as string | null,
    onReset: jest.fn(),
    onJobSelect: jest.fn(),
    editingCueIndex: null as number | null,
    editingCueDraft: "",
    editingCueSurface: null as "video" | "transcript" | null,
    isSavingTranscript: false,
    beginEditingCue: jest.fn(),
    handleUpdateDraft: jest.fn(),
    saveEditingCue: jest.fn(async () => {}),
    cancelEditingCue: jest.fn(),
  };
}

describe("PreviewSection", () => {
  const setCurrentTime = jest.fn();
  let contextValue: ReturnType<typeof buildContext>;

  beforeEach(() => {
    jest.clearAllMocks();
    contextValue = buildContext();
    (useProcessContext as jest.Mock).mockImplementation(() => contextValue);
    (usePlaybackContext as jest.Mock).mockReturnValue({
      currentTime: 0,
      setCurrentTime,
    });
    window.scrollTo = jest.fn();
  });

  it("shows the placeholder state when no completed job is available", () => {
    render(<PreviewSection />);

    expect(screen.getByText("resultPreviewTitle")).toBeInTheDocument();
    expect(screen.queryByTestId("preview-player")).not.toBeInTheDocument();
  });

  it("opens the compact export menu and forwards only the requested public formats", () => {
    contextValue.selectedJob = {
      status: "completed",
      result_data: {
        transcribe_provider: "groq",
        transcribe_tier: "standard",
      },
    };

    render(<PreviewSection />);

    fireEvent.click(screen.getByTestId("preview-player"));
    expect(setCurrentTime).toHaveBeenCalledWith(12.5);

    const inlineEditorBridge = screen.getByTestId("inline-editor-bridge");
    expect(inlineEditorBridge).toHaveAttribute("data-source-cues", "1");
    fireEvent.click(inlineEditorBridge);
    expect(contextValue.beginEditingCue).toHaveBeenCalledWith(0, "video");

    fireEvent.click(screen.getByTestId("position-on-video"));
    fireEvent.click(screen.getByTestId("cue-position-on-video"));
    fireEvent.click(screen.getByTestId("resize-on-video"));
    expect(contextValue.changeCuePosition).toHaveBeenNthCalledWith(
      1,
      0,
      42,
      "all",
    );
    expect(contextValue.changeCuePosition).toHaveBeenNthCalledWith(
      2,
      0,
      43,
      "cue",
    );
    expect(contextValue.setSubtitleSize).toHaveBeenCalledWith(115);
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();

    // REGRESSION: persistent transport controls covered the video and
    // subtitles on narrow mobile screens. Playback is gesture-first now.
    expect(
      screen.queryByTestId("editor-preview-controls"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("subtitlesReady")).not.toBeInTheDocument();
    expect(screen.queryByText("liveOutputSubtitle")).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("subtitle-direct-manipulation-hint"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("subtitle-touch-manipulation-hint"),
    ).not.toBeInTheDocument();

    const newVideoButton = screen.getByRole("button", {
      name: "newVideoButton",
    });
    const exportButton = screen.getByRole("button", {
      name: "exportMenuButton",
    });
    expect(
      newVideoButton.compareDocumentPosition(exportButton) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.queryByTestId("editor-export-menu")).not.toBeInTheDocument();
    expect(screen.queryByTestId("editor-export-panel")).not.toBeInTheDocument();

    fireEvent.click(exportButton);
    expect(screen.getByTestId("editor-export-menu")).toBeInTheDocument();
    expect(document.documentElement.style.overflow).toBe("hidden");
    expect(document.body.style.position).toBe("fixed");

    // REGRESSION: export choices used to permanently consume a large block
    // below the editor. They now appear on demand in two clear groups.
    const videoExports = screen.getByTestId("video-export-group");
    const subtitleExports = screen.getByTestId("subtitle-export-group");
    expect(
      within(videoExports).getByText("exportVideoTitle"),
    ).toBeInTheDocument();
    expect(
      within(videoExports).getByTestId("download-720p-btn"),
    ).toBeInTheDocument();
    expect(
      within(videoExports).getByTestId("download-1080p-btn"),
    ).toBeInTheDocument();
    expect(
      within(videoExports).getByTestId("download-4k-btn"),
    ).toBeInTheDocument();
    expect(
      within(videoExports).queryByTestId("srt-btn"),
    ).not.toBeInTheDocument();
    expect(
      within(subtitleExports).getByText("exportSubtitlesTitle"),
    ).toBeInTheDocument();
    expect(within(subtitleExports).getByTestId("srt-btn")).toBeInTheDocument();
    expect(within(subtitleExports).getByTestId("txt-btn")).toBeInTheDocument();
    expect(
      within(subtitleExports).queryByTestId("vtt-btn"),
    ).not.toBeInTheDocument();
    expect(
      within(subtitleExports).queryByTestId("download-1080p-btn"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("temporaryWorkspaceExportNote"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("srt-btn"));
    expect(screen.queryByTestId("editor-export-menu")).not.toBeInTheDocument();
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.body.style.position).toBe("");

    fireEvent.click(exportButton);
    fireEvent.click(screen.getByTestId("txt-btn"));
    fireEvent.click(exportButton);
    fireEvent.click(screen.getByTestId("download-720p-btn"));
    fireEvent.click(exportButton);
    fireEvent.click(screen.getByTestId("download-1080p-btn"));
    fireEvent.click(exportButton);
    fireEvent.click(screen.getByTestId("download-4k-btn"));

    expect(contextValue.handleExport).toHaveBeenCalledWith("srt");
    expect(contextValue.handleExport).toHaveBeenCalledWith("txt");
    expect(contextValue.handleExport).toHaveBeenCalledWith("720x1280");
    expect(contextValue.handleExport).toHaveBeenCalledWith("1080x1920");
    expect(contextValue.handleExport).toHaveBeenCalledWith("2160x3840");
    expect(screen.getByTestId("sidebar")).toBeInTheDocument();

    // REGRESSION: preview and exports must remain separate layout regions.
    expect(screen.getByTestId("completed-editor")).toBeInTheDocument();
    expect(screen.getByTestId("editor-preview-panel")).toBeInTheDocument();
    expect(
      document.querySelector(".editor-preview-meta"),
    ).not.toBeInTheDocument();
    expect(
      document.querySelector(".editor-model-pill"),
    ).not.toBeInTheDocument();
    expect(
      document.querySelector(".editor-aspect-pill"),
    ).not.toBeInTheDocument();
  });

  it("renders export errors when the provider surfaces one", () => {
    contextValue.selectedJob = {
      status: "completed",
      result_data: {
        transcribe_provider: "groq",
        transcribe_tier: "standard",
      },
    };
    contextValue.exportError = "Export failed";

    render(<PreviewSection />);

    fireEvent.click(screen.getByRole("button", { name: "exportMenuButton" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Export failed");
  });

  it("shows an accessible live progress bar while rendering an export", () => {
    contextValue.selectedJob = {
      status: "completed",
      result_data: {},
    };
    contextValue.exportingResolutions = { "1080x1920": true };
    contextValue.exportProgress = { "1080x1920": 42 };

    render(<PreviewSection />);

    const progress = screen.getByRole("progressbar", {
      name: "exportProgressLabel",
    });
    expect(progress).toHaveAttribute("aria-valuenow", "42");
    expect(screen.getByTestId("export-progress")).toHaveTextContent("42%");
  });

  it("uses the compact live-preview workspace for styles and previews the public export name", () => {
    contextValue.selectedJob = {
      status: "completed",
      result_data: {
        original_filename: "Interview.final.MOV",
      },
    };
    contextValue.activeSidebarTab = "styles";

    render(<PreviewSection />);

    // REGRESSION: mobile styling used to render below the export cards,
    // separating the controls from the video they update.
    expect(screen.getByTestId("editor-workspace")).toHaveClass(
      "editor-workspace-style-mode",
    );
    fireEvent.click(screen.getByRole("button", { name: "exportMenuButton" }));
    expect(screen.getByTestId("export-filename-preview")).toHaveTextContent(
      "Interview.final_subs.mp4",
    );

    const workspace = screen.getByTestId("editor-workspace");
    const actionBar = document.querySelector(".editor-ready-actions");
    expect(actionBar).not.toBeNull();
    expect(
      actionBar!.compareDocumentPosition(workspace) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.queryByTestId("editor-export-panel")).not.toBeInTheDocument();
  });

  it("opens the new video flow and resets the workflow when confirmed", () => {
    contextValue.selectedJob = {
      status: "completed",
      result_data: {
        transcribe_provider: "groq",
        transcribe_tier: "pro",
      },
    };

    render(<PreviewSection />);

    fireEvent.click(screen.getByRole("button", { name: "newVideoButton" }));
    fireEvent.click(screen.getByRole("button", { name: "confirm-new-video" }));

    expect(contextValue.onReset).toHaveBeenCalled();
    expect(contextValue.onJobSelect).toHaveBeenCalledWith(null);
    expect(window.scrollTo).toHaveBeenCalledWith({
      top: 0,
      behavior: "smooth",
    });
  });

  it("does not repeat the workflow step heading inside the completed editor", () => {
    contextValue.selectedJob = {
      status: "completed",
      result_data: {
        transcribe_provider: "groq",
        transcribe_tier: "standard",
      },
    };

    render(<PreviewSection />);

    // REGRESSION: workflow progress now has one canonical home above the editor.
    expect(screen.queryByText("step3Label")).not.toBeInTheDocument();
    expect(screen.getByTestId("completed-editor")).toBeInTheDocument();
  });
});
