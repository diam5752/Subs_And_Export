export const previewPlayerBaseProps = {
  videoUrl: "blob:test",
  cues: [],
  settings: {
    position: 20,
    color: "#FFFF00",
    fontSize: 100,
    karaoke: true,
    maxLines: 2,
    shadowStrength: 4,
  },
};

function mockResizeObserver() {
  if (typeof window.ResizeObserver !== "undefined") return;
  class ResizeObserverMock {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (window as any).ResizeObserver = ResizeObserverMock;
}

function mockPointerEvent() {
  if (typeof window.PointerEvent !== "undefined") return;

  class PointerEventMock extends MouseEvent {
    readonly pointerId: number;
    readonly pointerType: string;
    readonly isPrimary: boolean;

    constructor(type: string, params: PointerEventInit = {}) {
      super(type, params);
      this.pointerId = params.pointerId ?? 0;
      this.pointerType = params.pointerType ?? "";
      this.isPrimary = params.isPrimary ?? false;
    }
  }

  Object.defineProperty(window, "PointerEvent", {
    configurable: true,
    value: PointerEventMock,
  });
}

export function installPreviewPlayerTestEnvironment() {
  beforeAll(() => {
    mockResizeObserver();
    mockPointerEvent();
    Object.defineProperty(window.HTMLMediaElement.prototype, "play", {
      configurable: true,
      value: jest.fn().mockResolvedValue(undefined),
    });
    Object.defineProperty(window.HTMLMediaElement.prototype, "pause", {
      configurable: true,
      value: jest.fn(),
    });
  });

  afterEach(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    delete (HTMLVideoElement.prototype as any).requestVideoFrameCallback;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    delete (HTMLVideoElement.prototype as any).cancelVideoFrameCallback;
    jest.restoreAllMocks();
  });
}
