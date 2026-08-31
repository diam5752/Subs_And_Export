import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

import { I18nProvider } from "@/context/I18nContext";
import { api } from "@/lib/api";
import { ProcessProvider, useProcessContext } from "../ProcessContext";

jest.mock("@/lib/api", () => ({
  API_BASE: "http://localhost:8080",
  api: {
    updateJobTranscription: jest.fn(),
  },
}));

const selectedJob = {
  id: "job-1",
  status: "completed",
  progress: 100,
  message: null,
  created_at: Date.now(),
  updated_at: Date.now(),
  result_data: {
    video_path: "/static/artifacts/job-1/processed.mp4",
    artifacts_dir: "/static/artifacts/job-1",
    public_url: "/static/artifacts/job-1/processed.mp4",
  },
};

const providerProps = {
  selectedFile: null,
  onFileSelect: jest.fn(),
  isProcessing: false,
  progress: 0,
  statusMessage: "",
  error: "",
  onStartProcessing: jest.fn(async () => {}),
  onReprocessJob: jest.fn(async () => {}),
  onReset: jest.fn(),
  selectedJob,
  onJobSelect: jest.fn(),
  statusStyles: {},
  buildStaticUrl: jest.fn(() => null),
  totalJobs: 1,
};

function PositionHarness() {
  const {
    cues,
    setCues,
    subtitlePosition,
    transcriptSaveError,
    changeCuePosition,
    commitCuePosition,
    resetCuePosition,
  } = useProcessContext();
  const seed = () =>
    setCues([
      { start: 0, end: 2, text: "FIRST PHRASE" },
      { start: 2, end: 4, text: "SECOND PHRASE", position: 74 },
      { start: 4, end: 6, text: "THIRD PHRASE" },
    ]);
  return (
    <div>
      <button type="button" onClick={seed}>
        seed-positioned-transcript
      </button>
      <button
        type="button"
        onClick={() => {
          changeCuePosition(1, 80);
          void commitCuePosition(1);
        }}
      >
        move-selected-cue
      </button>
      <button type="button" onClick={() => void resetCuePosition(1)}>
        reset-selected-cue
      </button>
      <button
        type="button"
        onClick={() => {
          changeCuePosition(1, 84, "all");
          void commitCuePosition(1, "all");
        }}
      >
        move-all-cues
      </button>
      <div data-testid="cue-positions">
        {cues.map((cue) => cue.position ?? "shared").join(",")}
      </div>
      <div data-testid="shared-position">{subtitlePosition}</div>
      <div data-testid="transcript-save-error">{transcriptSaveError ?? ""}</div>
    </div>
  );
}

function TestBed() {
  return (
    <I18nProvider initialLocale="en">
      <ProcessProvider {...providerProps}>
        <PositionHarness />
      </ProcessProvider>
    </I18nProvider>
  );
}

describe("ProcessProvider cue positioning", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    (api.updateJobTranscription as jest.Mock).mockResolvedValue({
      status: "ok",
    });
  });

  it("persists and resets only the selected phrase override", async () => {
    render(<TestBed />);
    fireEvent.click(
      screen.getByRole("button", { name: "seed-positioned-transcript" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "move-selected-cue" }));

    await waitFor(() => {
      expect(api.updateJobTranscription).toHaveBeenCalledWith("job-1", [
        expect.not.objectContaining({ position: expect.anything() }),
        expect.objectContaining({ text: "SECOND PHRASE", position: 80 }),
        expect.not.objectContaining({ position: expect.anything() }),
      ]);
    });
    expect(screen.getByTestId("cue-positions")).toHaveTextContent(
      "shared,80,shared",
    );

    fireEvent.click(screen.getByRole("button", { name: "reset-selected-cue" }));
    await waitFor(() => {
      expect(screen.getByTestId("cue-positions")).toHaveTextContent(
        "shared,shared,shared",
      );
    });
    const resetPayload = (
      api.updateJobTranscription as jest.Mock
    ).mock.calls.at(-1)?.[1];
    expect(resetPayload[1]).not.toHaveProperty("position");
  });

  it("moves shared and custom positions by the same delta", async () => {
    render(<TestBed />);
    fireEvent.click(
      screen.getByRole("button", { name: "seed-positioned-transcript" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "move-all-cues" }));

    await waitFor(() => {
      expect(screen.getByTestId("shared-position")).toHaveTextContent("30");
      expect(screen.getByTestId("cue-positions")).toHaveTextContent(
        "shared,84,shared",
      );
    });
    expect(api.updateJobTranscription).toHaveBeenCalledWith(
      "job-1",
      expect.arrayContaining([
        expect.objectContaining({ text: "SECOND PHRASE", position: 84 }),
      ]),
    );
  });

  it("rolls back shared and cue positions when persistence fails", async () => {
    (api.updateJobTranscription as jest.Mock).mockRejectedValueOnce(
      new Error("Save unavailable"),
    );
    render(<TestBed />);
    fireEvent.click(
      screen.getByRole("button", { name: "seed-positioned-transcript" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "move-all-cues" }));

    await waitFor(() => {
      expect(screen.getByTestId("transcript-save-error")).toHaveTextContent(
        "Save unavailable",
      );
    });
    expect(screen.getByTestId("shared-position")).toHaveTextContent("20");
    expect(screen.getByTestId("cue-positions")).toHaveTextContent(
      "shared,74,shared",
    );
  });
});
