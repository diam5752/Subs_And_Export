/* eslint-disable @next/next/no-img-element */
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { PreviewPlayer } from "@/components/PreviewPlayer";
import {
  installPreviewPlayerTestEnvironment,
  previewPlayerBaseProps as baseProps,
} from "../../../test-support/previewPlayerTestSupport";

jest.mock("next/image", () => ({
  __esModule: true,
  default: (props: React.ImgHTMLAttributes<HTMLImageElement>) => (
    <img {...props} alt={props.alt ?? ""} />
  ),
}));

describe("PreviewPlayer editing gestures", () => {
  installPreviewPlayerTestEnvironment();

  it("plays at 2x only while a long press is held", () => {
    jest.useFakeTimers();
    try {
      const { container } = render(<PreviewPlayer {...baseProps} />);
      const video = container.querySelector("video") as HTMLVideoElement;
      Object.defineProperty(video, "paused", {
        configurable: true,
        value: false,
      });
      video.playbackRate = 1;

      fireEvent.pointerDown(video, {
        button: 0,
        pointerId: 3,
        pointerType: "touch",
        isPrimary: true,
        clientX: 100,
        clientY: 100,
      });
      act(() => {
        jest.advanceTimersByTime(400);
      });

      expect(video.playbackRate).toBe(1);
      expect(
        screen.queryByTestId("preview-gesture-feedback"),
      ).not.toBeInTheDocument();

      act(() => {
        jest.advanceTimersByTime(100);
      });

      expect(video.playbackRate).toBe(2);
      expect(screen.getByTestId("preview-gesture-feedback")).toHaveTextContent(
        "2×",
      );

      fireEvent.pointerUp(video, {
        button: 0,
        pointerId: 3,
        pointerType: "touch",
        isPrimary: true,
        clientX: 100,
        clientY: 100,
      });
      expect(video.playbackRate).toBe(1);
      expect(
        screen.queryByTestId("preview-gesture-feedback"),
      ).not.toBeInTheDocument();
    } finally {
      jest.useRealTimers();
    }
  });

  it("pauses playback and maps the visible subtitle to its editable source cue", () => {
    const onBeginEdit = jest.fn();
    const cue = {
      start: 0,
      end: 2,
      text: "editable subtitle",
      words: [
        { start: 0, end: 1, text: "editable" },
        { start: 1, end: 2, text: "subtitle" },
      ],
    };

    const { container } = render(
      <PreviewPlayer
        {...baseProps}
        cues={[cue]}
        subtitleEditor={{
          cues: [cue],
          editingCueIndex: null,
          draftText: "",
          isSaving: false,
          labels: {
            editAction: "Edit active subtitle",
            title: "Edit subtitle",
            textarea: "Subtitle text",
            save: "Save",
            cancel: "Cancel",
            shortcut: "Ctrl+Enter to save",
            saving: "Saving…",
          },
          onBeginEdit,
          onChange: jest.fn(),
          onSave: jest.fn(),
          onCancel: jest.fn(),
        }}
      />,
    );

    const video = container.querySelector("video") as HTMLVideoElement;
    fireEvent.click(
      screen.getByRole("button", { name: "Edit active subtitle" }),
    );

    expect(video.pause).toHaveBeenCalled();
    expect(onBeginEdit).toHaveBeenCalledWith(0);
  });

  it("keeps playback running during direct subtitle positioning", () => {
    // VEED-style direct manipulation stays on the live canvas. The overlay
    // pins the gesture to its source cue instead of pausing the player.
    const onPositionChange = jest.fn();
    const { container } = render(
      <PreviewPlayer
        {...baseProps}
        cues={[{ start: 0, end: 2, text: "move me" }]}
        subtitleTransformControls={{
          labels: {
            move: "Move subtitles",
            resize: "Resize subtitles",
          },
          onPositionChange,
          onSizeChange: jest.fn(),
        }}
      />,
    );

    const video = container.querySelector("video") as HTMLVideoElement;
    (video.play as jest.Mock).mockClear();
    (video.pause as jest.Mock).mockClear();
    const overlay = screen.getByTestId("subtitle-overlay");
    fireEvent.pointerDown(overlay, {
      button: 0,
      pointerId: 10,
      clientX: 300,
      clientY: 900,
    });
    fireEvent.pointerMove(overlay, {
      pointerId: 10,
      clientX: 300,
      clientY: 800,
    });

    expect(video.pause).not.toHaveBeenCalled();
    expect(video.play).not.toHaveBeenCalled();
    expect(onPositionChange).toHaveBeenCalledWith(0, expect.any(Number));
  });
});
