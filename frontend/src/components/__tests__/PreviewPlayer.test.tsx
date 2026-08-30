/* eslint-disable @next/next/no-img-element */
import React from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import "@testing-library/jest-dom";
import {
  PreviewPlayer,
  type PreviewPlayerHandle,
} from "@/components/PreviewPlayer";
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

describe("PreviewPlayer", () => {
  installPreviewPlayerTestEnvironment();

  it("preserves normal page gestures when no subtitle can be pinched", () => {
    const { container } = render(<PreviewPlayer {...baseProps} />);
    expect(container.firstElementChild).toHaveAttribute(
      "data-subtitle-pinch-enabled",
      "false",
    );
  });

  it("uses requestVideoFrameCallback for high-res time sync when available", () => {
    const requestVideoFrameCallback = jest.fn().mockReturnValue(123);
    const cancelVideoFrameCallback = jest.fn();

    Object.defineProperty(
      HTMLVideoElement.prototype,
      "requestVideoFrameCallback",
      {
        value: requestVideoFrameCallback,
        configurable: true,
      },
    );
    Object.defineProperty(
      HTMLVideoElement.prototype,
      "cancelVideoFrameCallback",
      {
        value: cancelVideoFrameCallback,
        configurable: true,
      },
    );

    const { container, unmount } = render(<PreviewPlayer {...baseProps} />);
    const video = container.querySelector("video");
    expect(video).not.toBeNull();

    fireEvent.play(video as HTMLVideoElement);
    expect(requestVideoFrameCallback).toHaveBeenCalledTimes(1);

    unmount();
    expect(cancelVideoFrameCallback).toHaveBeenCalledWith(123);
  });

  it("falls back to requestAnimationFrame when requestVideoFrameCallback is unavailable", () => {
    const requestAnimationFrameSpy = jest
      .spyOn(window, "requestAnimationFrame")
      .mockReturnValue(456);
    const cancelAnimationFrameSpy = jest
      .spyOn(window, "cancelAnimationFrame")
      .mockImplementation(() => {});

    const { container, unmount } = render(<PreviewPlayer {...baseProps} />);
    const video = container.querySelector("video");
    expect(video).not.toBeNull();

    fireEvent.play(video as HTMLVideoElement);
    expect(requestAnimationFrameSpy).toHaveBeenCalledTimes(1);

    unmount();
    expect(cancelAnimationFrameSpy).toHaveBeenCalledWith(456);
  });

  it("renders the watermark and reports time updates", async () => {
    const onTimeUpdate = jest.fn();
    const { container } = render(
      <PreviewPlayer
        {...baseProps}
        settings={{ ...baseProps.settings, watermarkEnabled: true }}
        onTimeUpdate={onTimeUpdate}
      />,
    );

    const watermark = screen.getByAltText("gsubs watermark");
    expect(watermark).toHaveAttribute("src", "/gsubs-watermark.png");
    expect(watermark.parentElement).toHaveClass("w-[30%]");

    const video = container.querySelector("video") as HTMLVideoElement;
    Object.defineProperty(video, "currentTime", {
      configurable: true,
      value: 4.2,
      writable: true,
    });

    fireEvent.timeUpdate(video);

    await waitFor(() => {
      expect(onTimeUpdate).toHaveBeenCalledWith(4.2);
    });
  });

  it("seeks through the imperative handle and applies initial time on metadata load", () => {
    const playerRef = React.createRef<PreviewPlayerHandle>();
    const { container } = render(
      <PreviewPlayer {...baseProps} ref={playerRef} initialTime={2} />,
    );

    const video = container.querySelector("video") as HTMLVideoElement;
    Object.defineProperty(video, "currentTime", {
      configurable: true,
      value: 0,
      writable: true,
    });

    fireEvent.loadedMetadata(video);
    expect(video.currentTime).toBeCloseTo(2, 4);

    act(() => {
      playerRef.current?.seekTo(7.5);
    });
    expect(video.currentTime).toBeCloseTo(7.5, 4);

    act(() => {
      playerRef.current?.pause();
    });
    expect(video.pause).toHaveBeenCalled();
  });

  it("primes the first frame when a paused iOS preview starts at zero", () => {
    // REGRESSION: WebKit stops at HAVE_METADATA for preload="metadata",
    // leaving a completed video black until the user starts playback.
    const { container } = render(
      <PreviewPlayer {...baseProps} initialTime={0} />,
    );

    const video = container.querySelector("video") as HTMLVideoElement;
    Object.defineProperty(video, "currentTime", {
      configurable: true,
      value: 0,
      writable: true,
    });
    Object.defineProperty(video, "duration", {
      configurable: true,
      value: 8.634,
    });

    fireEvent.loadedMetadata(video);

    expect(video.currentTime).toBeCloseTo(0.001, 4);
  });

  it("keeps native controls disabled and toggles playback with a tap gesture", () => {
    // REGRESSION: iOS Safari's native transport overlay covered the
    // subtitles with play, skip, volume, and progress controls.
    const playerRef = React.createRef<PreviewPlayerHandle>();
    const onPlaybackStatusChange = jest.fn();
    const { container } = render(
      <PreviewPlayer
        {...baseProps}
        ref={playerRef}
        playbackToggleLabel="Toggle preview"
        onPlaybackStatusChange={onPlaybackStatusChange}
      />,
    );

    const video = container.querySelector("video") as HTMLVideoElement;
    expect(video).not.toHaveAttribute("controls");
    expect(video).toHaveAttribute("playsinline");
    expect(video).toHaveAttribute("preload", "metadata");
    expect(video).toHaveAttribute("aria-label", "Toggle preview");
    expect(video).toHaveAttribute("disablepictureinpicture");
    expect(video).toHaveAttribute("disableremoteplayback");

    (video.play as jest.Mock).mockClear();
    fireEvent.pointerDown(video, {
      button: 0,
      pointerId: 1,
      pointerType: "touch",
      isPrimary: true,
      clientX: 100,
      clientY: 100,
    });
    fireEvent.pointerUp(video, {
      button: 0,
      pointerId: 1,
      pointerType: "touch",
      isPrimary: true,
      clientX: 100,
      clientY: 100,
    });
    expect(video.play).toHaveBeenCalled();

    act(() => {
      playerRef.current?.toggleMuted();
    });
    expect(video.muted).toBe(true);

    fireEvent.play(video);
    expect(onPlaybackStatusChange).toHaveBeenCalled();
  });

  it("honors rapid play-pause intent while the native play request is pending", async () => {
    // REGRESSION: mobile Safari can keep `paused` true until a play request
    // settles. Two quick taps must still mean play, then pause.
    let paused = true;
    let resolvePlay: (() => void) | undefined;
    const pendingPlay = new Promise<void>((resolve) => {
      resolvePlay = resolve;
    });
    const { container } = render(<PreviewPlayer {...baseProps} />);
    const video = container.querySelector("video") as HTMLVideoElement;
    Object.defineProperty(video, "paused", {
      configurable: true,
      get: () => paused,
    });
    const playSpy = jest.spyOn(video, "play").mockReturnValue(pendingPlay);
    const pauseSpy = jest.spyOn(video, "pause").mockImplementation(() => {
      paused = true;
    });
    playSpy.mockClear();
    pauseSpy.mockClear();

    for (const pointerId of [41, 42]) {
      fireEvent.pointerDown(video, {
        button: 0,
        pointerId,
        pointerType: "touch",
        isPrimary: true,
        clientX: 100,
        clientY: 100,
      });
      fireEvent.pointerUp(video, {
        button: 0,
        pointerId,
        pointerType: "touch",
        isPrimary: true,
        clientX: 100,
        clientY: 100,
      });
    }

    expect(playSpy).toHaveBeenCalledTimes(1);
    expect(pauseSpy).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolvePlay?.();
      await pendingPlay;
    });

    // WebKit can deliver the native play event after the second tap. The
    // latest pause intent must win and immediately stop that stale start.
    paused = false;
    fireEvent.play(video);
    expect(pauseSpy).toHaveBeenCalledTimes(2);

    fireEvent.pause(video);
    playSpy.mockClear();
    pauseSpy.mockClear();

    fireEvent.pointerDown(video, {
      button: 0,
      pointerId: 45,
      pointerType: "touch",
      isPrimary: true,
      clientX: 100,
      clientY: 100,
    });
    fireEvent.pointerUp(video, {
      button: 0,
      pointerId: 45,
      pointerType: "touch",
      isPrimary: true,
      clientX: 100,
      clientY: 100,
    });

    expect(playSpy).toHaveBeenCalledTimes(1);
    expect(pauseSpy).not.toHaveBeenCalled();
  });

  it("honors an immediate play request while the native pause state is delayed", () => {
    // REGRESSION: WebKit may report the old `paused` value for the next
    // input event. User intent, rather than that delayed property, owns the
    // play-pause sequence.
    const { container } = render(<PreviewPlayer {...baseProps} />);
    const video = container.querySelector("video") as HTMLVideoElement;
    Object.defineProperty(video, "paused", {
      configurable: true,
      get: () => false,
    });
    const playSpy = jest.spyOn(video, "play").mockResolvedValue(undefined);
    const pauseSpy = jest.spyOn(video, "pause").mockImplementation(() => {});
    playSpy.mockClear();
    pauseSpy.mockClear();

    for (const pointerId of [43, 44]) {
      fireEvent.pointerDown(video, {
        button: 0,
        pointerId,
        pointerType: "touch",
        isPrimary: true,
        clientX: 100,
        clientY: 100,
      });
      fireEvent.pointerUp(video, {
        button: 0,
        pointerId,
        pointerType: "touch",
        isPrimary: true,
        clientX: 100,
        clientY: 100,
      });
    }

    expect(pauseSpy).toHaveBeenCalledTimes(1);
    expect(playSpy).toHaveBeenCalledTimes(1);
  });

  it("resynchronizes after a native mobile playback interruption", async () => {
    // REGRESSION: iOS/Android can pause media from the OS or backgrounding.
    // The next tap must resume in one action, not call pause again.
    let paused = true;
    const { container } = render(<PreviewPlayer {...baseProps} />);
    const video = container.querySelector("video") as HTMLVideoElement;
    Object.defineProperty(video, "paused", {
      configurable: true,
      get: () => paused,
    });
    const playSpy = jest.spyOn(video, "play").mockImplementation(() => {
      paused = false;
      return Promise.resolve();
    });
    const pauseSpy = jest.spyOn(video, "pause").mockImplementation(() => {
      paused = true;
    });
    playSpy.mockClear();
    pauseSpy.mockClear();

    fireEvent.pointerDown(video, {
      button: 0,
      pointerId: 48,
      pointerType: "touch",
      isPrimary: true,
      clientX: 100,
      clientY: 100,
    });
    fireEvent.pointerUp(video, {
      button: 0,
      pointerId: 48,
      pointerType: "touch",
      isPrimary: true,
      clientX: 100,
      clientY: 100,
    });
    fireEvent.play(video);
    await act(async () => {
      await Promise.resolve();
    });

    paused = true;
    fireEvent.pause(video);
    playSpy.mockClear();
    pauseSpy.mockClear();

    fireEvent.pointerDown(video, {
      button: 0,
      pointerId: 49,
      pointerType: "touch",
      isPrimary: true,
      clientX: 100,
      clientY: 100,
    });
    fireEvent.pointerUp(video, {
      button: 0,
      pointerId: 49,
      pointerType: "touch",
      isPrimary: true,
      clientX: 100,
      clientY: 100,
    });

    expect(playSpy).toHaveBeenCalledTimes(1);
    expect(pauseSpy).not.toHaveBeenCalled();
  });

  it("scrubs relatively with a horizontal drag and only shows feedback while dragging", () => {
    const onTimeUpdate = jest.fn();
    const { container } = render(
      <PreviewPlayer {...baseProps} onTimeUpdate={onTimeUpdate} />,
    );
    const video = container.querySelector("video") as HTMLVideoElement;
    Object.defineProperty(video, "duration", {
      configurable: true,
      value: 100,
    });
    Object.defineProperty(video, "currentTime", {
      configurable: true,
      value: 20,
      writable: true,
    });
    Object.defineProperty(video, "paused", {
      configurable: true,
      value: false,
    });
    jest.spyOn(video, "getBoundingClientRect").mockReturnValue({
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      right: 200,
      bottom: 356,
      width: 200,
      height: 356,
      toJSON: () => ({}),
    });

    fireEvent.pointerDown(video, {
      button: 0,
      pointerId: 2,
      pointerType: "touch",
      isPrimary: true,
      clientX: 100,
      clientY: 100,
    });
    fireEvent.pointerMove(video, {
      button: 0,
      pointerId: 2,
      pointerType: "touch",
      isPrimary: true,
      clientX: 150,
      clientY: 102,
    });

    // A quarter-screen drag moves within a bounded relative seek window,
    // instead of jumping across the whole video.
    expect(video.currentTime).toBeCloseTo(26.25, 2);
    expect(onTimeUpdate).toHaveBeenLastCalledWith(26.25);
    expect(screen.getByTestId("preview-gesture-feedback")).toHaveTextContent(
      "+0:06",
    );
    expect(screen.getByTestId("preview-gesture-feedback")).toHaveTextContent(
      "0:26 / 1:40",
    );
    expect(screen.getByTestId("preview-gesture-feedback")).toHaveTextContent(
      "−1:13",
    );
    expect(screen.getByTestId("preview-gesture-feedback")).toHaveAttribute(
      "data-progress",
      "26",
    );
    expect(screen.getByTestId("preview-seek-progress")).toHaveStyle({
      width: "26.25%",
    });

    fireEvent.pointerUp(video, {
      button: 0,
      pointerId: 2,
      pointerType: "touch",
      isPrimary: true,
      clientX: 150,
      clientY: 102,
    });
    expect(
      screen.queryByTestId("preview-gesture-feedback"),
    ).not.toBeInTheDocument();
  });

  it("does not restart playback after a cancelled mobile scrub", () => {
    // REGRESSION: browser gesture arbitration can emit pointercancel. A
    // cancelled seek must stay paused instead of unexpectedly restarting.
    const { container } = render(<PreviewPlayer {...baseProps} />);
    const video = container.querySelector("video") as HTMLVideoElement;
    Object.defineProperty(video, "duration", {
      configurable: true,
      value: 100,
    });
    Object.defineProperty(video, "currentTime", {
      configurable: true,
      value: 20,
      writable: true,
    });
    Object.defineProperty(video, "paused", {
      configurable: true,
      value: false,
    });
    jest.spyOn(video, "getBoundingClientRect").mockReturnValue({
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      right: 200,
      bottom: 356,
      width: 200,
      height: 356,
      toJSON: () => ({}),
    });
    const playSpy = jest.spyOn(video, "play").mockClear();

    fireEvent.pointerDown(video, {
      button: 0,
      pointerId: 45,
      pointerType: "touch",
      isPrimary: true,
      clientX: 80,
      clientY: 100,
    });
    fireEvent.pointerMove(video, {
      button: 0,
      pointerId: 45,
      pointerType: "touch",
      isPrimary: true,
      clientX: 130,
      clientY: 101,
    });
    fireEvent.pointerCancel(video, {
      pointerId: 45,
      pointerType: "touch",
      isPrimary: true,
    });

    expect(playSpy).not.toHaveBeenCalled();
    expect(
      screen.queryByTestId("preview-gesture-feedback"),
    ).not.toBeInTheDocument();
  });

  it("owns a mixed-hit two-finger pinch without playing or scrubbing", () => {
    // REGRESSION: on a phone, one finger often lands beside the caption on
    // the video while the other lands on the text. Both belong to one
    // subtitle pinch gesture.
    jest.useFakeTimers();
    try {
      function StatefulPlayer() {
        const [fontSize, setFontSize] = React.useState(100);
        return (
          <PreviewPlayer
            {...baseProps}
            cues={[{ start: 0, end: 2, text: "pinch across targets" }]}
            settings={{ ...baseProps.settings, fontSize }}
            subtitleTransformControls={{
              labels: {
                move: "Move subtitles",
                resize: "Resize subtitles",
              },
              onPositionChange: jest.fn(),
              onSizeChange: setFontSize,
            }}
          />
        );
      }

      const { container } = render(<StatefulPlayer />);
      const video = container.querySelector("video") as HTMLVideoElement;
      const overlay = screen.getByTestId("subtitle-overlay");
      Object.defineProperty(video, "currentTime", {
        configurable: true,
        value: 0.5,
        writable: true,
      });
      const playSpy = jest.spyOn(video, "play").mockClear();
      expect(container.firstElementChild).toHaveAttribute(
        "data-subtitle-pinch-enabled",
        "true",
      );

      fireEvent.pointerDown(video, {
        button: 0,
        pointerId: 46,
        pointerType: "touch",
        isPrimary: true,
        clientX: 80,
        clientY: 180,
      });
      fireEvent.pointerDown(overlay, {
        button: 0,
        pointerId: 47,
        pointerType: "touch",
        isPrimary: false,
        clientX: 180,
        clientY: 180,
      });
      fireEvent.lostPointerCapture(video, {
        pointerId: 46,
        pointerType: "touch",
      });
      act(() => {
        jest.advanceTimersByTime(500);
      });
      fireEvent.pointerMove(overlay, {
        pointerId: 47,
        pointerType: "touch",
        isPrimary: false,
        clientX: 230,
        clientY: 180,
      });

      expect(screen.getByTestId("subtitle-overlay")).toHaveAttribute(
        "data-font-size",
        "150",
      );
      expect(video.playbackRate).toBe(1);
      expect(playSpy).not.toHaveBeenCalled();
      expect(video.currentTime).toBe(0.5);
      expect(
        screen.queryByTestId("preview-gesture-feedback"),
      ).not.toBeInTheDocument();

      fireEvent.pointerMove(overlay, {
        pointerId: 47,
        pointerType: "touch",
        isPrimary: false,
        clientX: 120,
        clientY: 180,
      });
      expect(screen.getByTestId("subtitle-overlay")).toHaveAttribute(
        "data-font-size",
        "50",
      );

      fireEvent.pointerUp(overlay, {
        pointerId: 47,
        pointerType: "touch",
        isPrimary: false,
        clientX: 120,
        clientY: 180,
      });
      fireEvent.pointerUp(video, {
        pointerId: 46,
        pointerType: "touch",
        isPrimary: true,
        clientX: 80,
        clientY: 180,
      });
    } finally {
      jest.useRealTimers();
    }
  });
});
