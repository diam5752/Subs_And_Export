import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { SubtitleOverlay } from "@/components/SubtitleOverlay";

function firePointer(
  element: Element,
  type: "pointerdown" | "pointermove" | "pointerup",
  init: MouseEventInit & { pointerId: number },
) {
  const event = new MouseEvent(type, {
    bubbles: true,
    cancelable: true,
    ...init,
  });
  Object.defineProperties(event, {
    pointerId: { configurable: true, value: init.pointerId },
    pointerType: { configurable: true, value: "mouse" },
  });
  fireEvent(element, event);
}

describe("SubtitleOverlay phrase positioning", () => {
  it("pins a live drag to the phrase active when playback advanced", () => {
    const onPositionChange = jest.fn();
    const onPositionCommit = jest.fn();

    function LiveOverlay() {
      const [currentTime, setCurrentTime] = React.useState(0.5);
      return (
        <>
          <button type="button" onClick={() => setCurrentTime(2.5)}>
            advance
          </button>
          <SubtitleOverlay
            currentTime={currentTime}
            cues={[
              { start: 0, end: 2, text: "first", sourceCueIndex: 3 },
              { start: 2, end: 4, text: "second", sourceCueIndex: 4 },
            ]}
            settings={{
              position: 20,
              color: "#FFFF00",
              fontSize: 100,
              karaoke: false,
              maxLines: 2,
              shadowStrength: 4,
            }}
            videoWidth={500}
            videoHeight={1000}
            transformControls={{
              labels: {
                move: "Move phrase",
                resize: "Resize subtitles",
              },
              onPositionChange,
              onPositionCommit,
              onSizeChange: jest.fn(),
            }}
          />
        </>
      );
    }

    render(<LiveOverlay />);
    const firstOverlay = screen.getByTestId("subtitle-overlay");
    firePointer(firstOverlay, "pointerdown", {
      button: 0,
      pointerId: 70,
      clientX: 250,
      clientY: 600,
    });
    fireEvent.click(screen.getByRole("button", { name: "advance" }));
    const currentOverlay = screen.getByTestId("subtitle-overlay");
    firePointer(currentOverlay, "pointermove", {
      pointerId: 70,
      clientX: 250,
      clientY: 500,
    });
    firePointer(currentOverlay, "pointerup", {
      pointerId: 70,
      clientX: 250,
      clientY: 500,
    });

    expect(onPositionChange).toHaveBeenCalledWith(3, 30);
    expect(onPositionCommit).toHaveBeenCalledWith(3);
  });

  it("renders a cue-local position and can reset only that phrase", () => {
    const onPositionReset = jest.fn();
    render(
      <SubtitleOverlay
        currentTime={2.5}
        cues={[
          { start: 0, end: 2, text: "shared" },
          {
            start: 2,
            end: 4,
            text: "custom",
            position: 77,
            sourceCueIndex: 8,
          },
        ]}
        settings={{
          position: 20,
          color: "#FFFF00",
          fontSize: 100,
          karaoke: false,
          maxLines: 2,
          shadowStrength: 4,
        }}
        transformControls={{
          labels: {
            move: "Move phrase",
            resize: "Resize subtitles",
            customPosition: "custom phrase position",
            resetPosition: "Use shared position",
          },
          onPositionChange: jest.fn(),
          onPositionReset,
          onSizeChange: jest.fn(),
        }}
      />,
    );

    const overlay = screen.getByTestId("subtitle-overlay");
    const moveHandle = screen.getByRole("slider", { name: "Move phrase" });
    expect(overlay).toHaveAttribute("data-position", "77");
    expect(overlay).toHaveAttribute("data-position-mode", "custom");
    expect(moveHandle).toHaveAttribute("aria-valuenow", "77");
    expect(moveHandle).toHaveAttribute(
      "aria-valuetext",
      "77% · custom phrase position",
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Use shared position" }),
    );
    expect(onPositionReset).toHaveBeenCalledWith(8);
  });
});
