import { validateVideoAspectRatio } from "../video";

function concatenateBytes(...chunks: Uint8Array[]): Uint8Array {
  const result = new Uint8Array(
    chunks.reduce((total, chunk) => total + chunk.length, 0),
  );
  let offset = 0;
  for (const chunk of chunks) {
    result.set(chunk, offset);
    offset += chunk.length;
  }
  return result;
}

function makeIsoBox(type: string, payload: Uint8Array): Uint8Array {
  const box = new Uint8Array(8 + payload.length);
  const view = new DataView(box.buffer);
  view.setUint32(0, box.length);
  for (let index = 0; index < 4; index += 1) {
    box[4 + index] = type.charCodeAt(index);
  }
  box.set(payload, 8);
  return box;
}

function makeExtendedIsoBox(type: string, payload: Uint8Array): Uint8Array {
  const box = new Uint8Array(16 + payload.length);
  const view = new DataView(box.buffer);
  view.setUint32(0, 1);
  for (let index = 0; index < 4; index += 1) {
    box[4 + index] = type.charCodeAt(index);
  }
  view.setUint32(8, 0);
  view.setUint32(12, box.length);
  box.set(payload, 16);
  return box;
}

function makeMovieHeader(version: 0 | 1 = 0): Uint8Array {
  const movieHeader = new Uint8Array(version === 1 ? 112 : 100);
  const movieHeaderView = new DataView(movieHeader.buffer);
  movieHeader[0] = version;
  const timescaleOffset = version === 1 ? 20 : 12;
  const durationOffset = version === 1 ? 24 : 16;
  movieHeaderView.setUint32(timescaleOffset, 1_000);
  if (version === 1) {
    movieHeaderView.setUint32(durationOffset, 0);
    movieHeaderView.setUint32(durationOffset + 4, 8_633);
  } else {
    movieHeaderView.setUint32(durationOffset, 8_633);
  }
  return movieHeader;
}

function makeTrackHeader({
  version = 0,
  width,
  height,
  quarterTurn = false,
}: {
  version?: 0 | 1;
  width: number;
  height: number;
  quarterTurn?: boolean;
}): Uint8Array {
  const trackHeader = new Uint8Array(version === 1 ? 96 : 84);
  const trackHeaderView = new DataView(trackHeader.buffer);
  trackHeader[0] = version;
  const matrixOffset = version === 1 ? 52 : 40;
  if (quarterTurn) {
    trackHeaderView.setInt32(matrixOffset + 4, 65_536);
    trackHeaderView.setInt32(matrixOffset + 12, -65_536);
  } else {
    trackHeaderView.setInt32(matrixOffset, 65_536);
    trackHeaderView.setInt32(matrixOffset + 16, 65_536);
  }
  trackHeaderView.setInt32(matrixOffset + 32, 0x4000_0000);
  const widthOffset = version === 1 ? 88 : 76;
  trackHeaderView.setUint32(widthOffset, width * 65_536);
  trackHeaderView.setUint32(widthOffset + 4, height * 65_536);
  return trackHeader;
}

function makeTrack({
  handlerType,
  width,
  height,
  version = 0,
  quarterTurn = false,
}: {
  handlerType: "vide" | "soun";
  width: number;
  height: number;
  version?: 0 | 1;
  quarterTurn?: boolean;
}): Uint8Array {
  const handler = new Uint8Array(24);
  for (const [index, character] of [...handlerType].entries()) {
    handler[8 + index] = character.charCodeAt(0);
  }
  return makeIsoBox(
    "trak",
    concatenateBytes(
      makeIsoBox(
        "tkhd",
        makeTrackHeader({ version, width, height, quarterTurn }),
      ),
      makeIsoBox("mdia", makeIsoBox("hdlr", handler)),
    ),
  );
}

function makeFileFromBytes(
  bytes: Uint8Array,
  name = "container-metadata.mp4",
  type = "video/mp4",
): File {
  return {
    name,
    type,
    size: bytes.length,
    slice: jest.fn((start = 0, end = bytes.length) => {
      const slice = bytes.slice(start, end);
      return {
        arrayBuffer: async () => slice.buffer,
      } as Blob;
    }),
  } as unknown as File;
}

function makeIsoBmffFile({
  version = 0,
  quarterTurn = false,
  audioFirst = false,
  extendedMovieBox = false,
  movieAfterMedia = false,
  omitFileType = false,
  duplicateMovieHeader = false,
}: {
  version?: 0 | 1;
  quarterTurn?: boolean;
  audioFirst?: boolean;
  extendedMovieBox?: boolean;
  movieAfterMedia?: boolean;
  omitFileType?: boolean;
  duplicateMovieHeader?: boolean;
} = {}): File {
  const visualTrack = makeTrack({
    handlerType: "vide",
    width: quarterTurn ? 1920 : 1080,
    height: quarterTurn ? 1080 : 1920,
    version,
    quarterTurn,
  });
  const audioTrack = makeTrack({
    handlerType: "soun",
    width: 4000,
    height: 4000,
  });
  const moviePayload = concatenateBytes(
    makeIsoBox("mvhd", makeMovieHeader(version)),
    ...(duplicateMovieHeader
      ? [makeIsoBox("mvhd", makeMovieHeader(version))]
      : []),
    ...(audioFirst ? [audioTrack] : []),
    visualTrack,
  );
  const movieBox = extendedMovieBox
    ? makeExtendedIsoBox("moov", moviePayload)
    : makeIsoBox("moov", moviePayload);

  const bytes = concatenateBytes(
    ...(omitFileType
      ? []
      : [
          makeIsoBox(
            "ftyp",
            new Uint8Array([0x69, 0x73, 0x6f, 0x6d, 0x00, 0x00, 0x02, 0x00]),
          ),
        ]),
    ...(movieAfterMedia ? [makeIsoBox("mdat", new Uint8Array(1_024))] : []),
    movieBox,
  );
  return makeFileFromBytes(bytes);
}

describe("video utils", () => {
  describe("validateVideoAspectRatio", () => {
    let mockVideo: HTMLVideoElement;
    let mockCanvas: HTMLCanvasElement;
    let mockContext: CanvasRenderingContext2D;
    const events: Record<string, () => void> = {};

    beforeEach(() => {
      events["loadedmetadata"] = () => {};
      events["durationchange"] = () => {};
      events["seeked"] = () => {};
      events["error"] = () => {};

      mockVideo = {
        videoWidth: 0,
        videoHeight: 0,
        duration: 10,
        currentTime: 0,
        preload: "",
        muted: false,
        playsInline: false,
        src: "",
        addEventListener: jest.fn((event, handler) => {
          events[event] = handler;
        }),
        load: jest.fn(),
        removeAttribute: jest.fn(),
      } as unknown as HTMLVideoElement;

      mockContext = {
        drawImage: jest.fn(),
      } as unknown as CanvasRenderingContext2D;

      mockCanvas = {
        width: 0,
        height: 0,
        getContext: jest.fn(() => mockContext),
        toDataURL: jest.fn(() => "data:image/jpeg;base64,test"),
      } as unknown as HTMLCanvasElement;

      jest
        .spyOn(document, "createElement")
        .mockImplementation((tagName: string) => {
          if (tagName === "video") return mockVideo;
          if (tagName === "canvas") return mockCanvas;
          return document.createElement(tagName);
        });

      global.URL.createObjectURL = jest.fn(() => "blob:test");
      global.URL.revokeObjectURL = jest.fn();
    });

    afterEach(() => {
      jest.useRealTimers();
      jest.restoreAllMocks();
    });

    async function validateUsingContainerMetadata(file: File) {
      jest.useFakeTimers();
      (mockVideo as unknown as { duration: number }).duration = Number.NaN;
      const promise = validateVideoAspectRatio(file);
      let settled = false;
      void promise.then(() => {
        settled = true;
      });

      await jest.advanceTimersByTimeAsync(9_999);
      expect(settled).toBe(false);
      await jest.advanceTimersByTimeAsync(1);
      return promise;
    }

    it("recovers when WebKit publishes a finite duration after early metadata", async () => {
      // REGRESSION: WebKit can publish loadedmetadata before duration is
      // finite. The old 1.2s frame fallback then resolved duration 0 and
      // disabled Start Processing permanently for a valid local MP4.
      jest.useFakeTimers();
      (mockVideo as unknown as { duration: number }).duration = Number.NaN;
      const file = new File(["video"], "delayed-metadata.mp4", {
        type: "video/mp4",
      });
      let settled = false;
      const promise = validateVideoAspectRatio(file).then((result) => {
        settled = true;
        return result;
      });

      events["loadedmetadata"]();
      // A valid local file can take longer than the old three-second
      // ceiling to publish finite metadata on a busy iOS/WebKit device.
      jest.advanceTimersByTime(4_000);
      await Promise.resolve();
      expect(settled).toBe(false);

      (mockVideo as unknown as { videoWidth: number }).videoWidth = 1080;
      (mockVideo as unknown as { videoHeight: number }).videoHeight = 1920;
      (mockVideo as unknown as { duration: number }).duration = 8.633333;
      events["durationchange"]();
      events["seeked"]();

      await expect(promise).resolves.toEqual({
        width: 1080,
        height: 1920,
        durationSeconds: 8.633333,
        aspectWarning: false,
        thumbnailUrl: "data:image/jpeg;base64,test",
      });
    });

    it("fails closed after a bounded timeout when metadata never becomes usable", async () => {
      // REGRESSION: a browser that emitted neither usable metadata nor a
      // terminal error left validation pending forever.
      jest.useFakeTimers();
      (mockVideo as unknown as { duration: number }).duration = Number.NaN;
      const file = new File(["invalid"], "invalid.mp4", { type: "video/mp4" });
      let result:
        Awaited<ReturnType<typeof validateVideoAspectRatio>> | undefined;
      void validateVideoAspectRatio(file).then((value) => {
        result = value;
      });

      await jest.runOnlyPendingTimersAsync();

      expect(result).toEqual({
        width: 0,
        height: 0,
        durationSeconds: 0,
        aspectWarning: true,
        thumbnailUrl: null,
      });
    });

    it("uses bounded ISO BMFF metadata when WebKit never publishes media metadata", async () => {
      // REGRESSION: CI WebKit can leave a valid local MP4 at duration NaN
      // for the entire media-element readiness window. Validation must
      // still use the file container metadata instead of blocking the
      // user or quoting the default 100-credit tier.
      const promise = validateUsingContainerMetadata(makeIsoBmffFile());

      await expect(promise).resolves.toEqual({
        width: 1080,
        height: 1920,
        durationSeconds: 8.633,
        aspectWarning: false,
        thumbnailUrl: null,
      });
    });

    it.each([
      ["version 1 fields", { version: 1 as const }],
      [
        "audio-first rotated video track",
        { audioFirst: true, quarterTurn: true },
      ],
      [
        "extended movie box after media data",
        { extendedMovieBox: true, movieAfterMedia: true },
      ],
    ])(
      "parses %s without trusting the native media element",
      async (_name, options) => {
        await expect(
          validateUsingContainerMetadata(makeIsoBmffFile(options)),
        ).resolves.toMatchObject({
          width: 1080,
          height: 1920,
          durationSeconds: 8.633,
          aspectWarning: false,
        });
      },
    );

    it("does not read the file when native video metadata is usable", async () => {
      const file = makeIsoBmffFile();
      const promise = validateVideoAspectRatio(file);
      (mockVideo as unknown as { videoWidth: number }).videoWidth = 1080;
      (mockVideo as unknown as { videoHeight: number }).videoHeight = 1920;

      events["loadedmetadata"]();
      events["seeked"]();

      await expect(promise).resolves.toMatchObject({
        width: 1080,
        height: 1920,
        durationSeconds: 10,
      });
      expect(file.slice).not.toHaveBeenCalled();
    });

    it("lets late native metadata finish while the container fallback is pending", async () => {
      jest.useFakeTimers();
      (mockVideo as unknown as { duration: number }).duration = Number.NaN;
      const file = makeIsoBmffFile();
      const promise = validateVideoAspectRatio(file);

      jest.advanceTimersByTime(10_000);
      (mockVideo as unknown as { videoWidth: number }).videoWidth = 1080;
      (mockVideo as unknown as { videoHeight: number }).videoHeight = 1920;
      (mockVideo as unknown as { duration: number }).duration = 8.633333;
      events["durationchange"]();
      await Promise.resolve();
      events["seeked"]();

      await expect(promise).resolves.toMatchObject({
        width: 1080,
        height: 1920,
        durationSeconds: 8.633333,
        thumbnailUrl: "data:image/jpeg;base64,test",
      });
    });

    it("lets late native metadata finish when the container read rejects", async () => {
      // REGRESSION: a failed asynchronous fallback read must re-check
      // native metadata before resolving. Otherwise WebKit can publish
      // usable metadata during the rejected read and still lose the
      // native thumbnail path.
      jest.useFakeTimers();
      (mockVideo as unknown as { duration: number }).duration = Number.NaN;
      let rejectRead: ((reason?: unknown) => void) | undefined;
      const file = makeIsoBmffFile();
      (file.slice as jest.Mock).mockImplementation(
        () =>
          ({
            arrayBuffer: () =>
              new Promise<ArrayBuffer>((_resolve, reject) => {
                rejectRead = reject;
              }),
          }) as Blob,
      );

      const promise = validateVideoAspectRatio(file);
      await jest.advanceTimersByTimeAsync(10_000);
      expect(rejectRead).toBeDefined();

      (mockVideo as unknown as { videoWidth: number }).videoWidth = 1080;
      (mockVideo as unknown as { videoHeight: number }).videoHeight = 1920;
      (mockVideo as unknown as { duration: number }).duration = 8.633333;
      events["durationchange"]();
      rejectRead?.(new Error("synthetic container read failure"));
      await Promise.resolve();
      events["seeked"]();

      await expect(promise).resolves.toMatchObject({
        width: 1080,
        height: 1920,
        durationSeconds: 8.633333,
        thumbnailUrl: "data:image/jpeg;base64,test",
      });
    });

    it.each([
      ["a missing file-type box", { omitFileType: true }],
      ["duplicate movie headers", { duplicateMovieHeader: true }],
    ])("fails closed for %s", async (_name, options) => {
      await expect(
        validateUsingContainerMetadata(makeIsoBmffFile(options)),
      ).resolves.toMatchObject({
        width: 0,
        height: 0,
        durationSeconds: 0,
        aspectWarning: true,
      });
    });

    it("does not read an oversized ISO BMFF movie box into memory", async () => {
      // REGRESSION: metadata fallback reads attacker-controlled local
      // files. Oversized box declarations must stay bounded instead of
      // allocating the declared payload.
      jest.useFakeTimers();
      (mockVideo as unknown as { duration: number }).duration = Number.NaN;
      const declaredMovieSize = 40 * 1024 * 1024;
      const fileTypeHeader = makeIsoBox(
        "ftyp",
        new Uint8Array([0x69, 0x73, 0x6f, 0x6d, 0x00, 0x00, 0x02, 0x00]),
      );
      const movieHeader = new Uint8Array(16);
      const movieHeaderView = new DataView(movieHeader.buffer);
      movieHeaderView.setUint32(0, declaredMovieSize);
      for (const [index, character] of [..."moov"].entries()) {
        movieHeader[4 + index] = character.charCodeAt(0);
      }
      const slice = jest.fn((start = 0) => {
        const bytes = start === 0 ? fileTypeHeader : movieHeader;
        return { arrayBuffer: async () => bytes.buffer } as Blob;
      });
      const file = {
        name: "oversized.mp4",
        type: "video/mp4",
        size: fileTypeHeader.length + declaredMovieSize,
        slice,
      } as unknown as File;

      const promise = validateVideoAspectRatio(file);
      await jest.advanceTimersByTimeAsync(10_000);

      await expect(promise).resolves.toMatchObject({
        durationSeconds: 0,
        thumbnailUrl: null,
      });
      expect(slice).toHaveBeenCalledTimes(2);
      expect(slice).toHaveBeenCalledWith(0, 16);
      expect(slice).toHaveBeenCalledWith(16, 32);
    });

    it("cancels stale metadata work and revokes the object URL", async () => {
      const controller = new AbortController();
      const promise = validateVideoAspectRatio(
        makeIsoBmffFile(),
        controller.signal,
      );

      controller.abort();

      await expect(promise).resolves.toMatchObject({ thumbnailUrl: null });
      expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:test");
    });

    it("keeps an unrecovered media error fail-closed until the readiness timeout", async () => {
      jest.useFakeTimers();
      (mockVideo as unknown as { duration: number }).duration = Number.NaN;
      const file = new File(["invalid"], "errored.mp4", { type: "video/mp4" });
      let result:
        Awaited<ReturnType<typeof validateVideoAspectRatio>> | undefined;
      void validateVideoAspectRatio(file).then((value) => {
        result = value;
      });

      events["error"]();
      await Promise.resolve();
      expect(result).toBeUndefined();

      await jest.runOnlyPendingTimersAsync();
      expect(result?.durationSeconds).toBe(0);
      expect(result?.aspectWarning).toBe(true);
      expect(result?.thumbnailUrl).toBeNull();
    });

    it("should validate valid 9:16 video", async () => {
      const file = new File([""], "test.mp4", { type: "video/mp4" });
      const promise = validateVideoAspectRatio(file);

      (mockVideo as unknown as { videoWidth: number }).videoWidth = 1080;
      (mockVideo as unknown as { videoHeight: number }).videoHeight = 1920;
      events["loadedmetadata"]();
      events["seeked"]();

      const result = await promise;
      expect(result).toEqual({
        width: 1080,
        height: 1920,
        durationSeconds: 10,
        aspectWarning: false,
        thumbnailUrl: "data:image/jpeg;base64,test",
      });
    });

    it("should warn for non-9:16 video", async () => {
      const file = new File([""], "test.mp4", { type: "video/mp4" });
      const promise = validateVideoAspectRatio(file);

      (mockVideo as unknown as { videoWidth: number }).videoWidth = 1920;
      (mockVideo as unknown as { videoHeight: number }).videoHeight = 1080;
      events["loadedmetadata"]();
      events["seeked"]();

      const result = await promise;
      expect(result.aspectWarning).toBe(true);
    });

    it("should handle video load errors", async () => {
      jest.useFakeTimers();
      const file = new File([""], "test.mp4", { type: "video/mp4" });
      const promise = validateVideoAspectRatio(file);

      events["error"]();
      await jest.runOnlyPendingTimersAsync();

      const result = await promise;
      expect(result).toEqual({
        width: 0,
        height: 0,
        durationSeconds: 10,
        aspectWarning: true,
        thumbnailUrl: null,
      });
    });

    it("should handle captureFrame with no video dimensions", async () => {
      const file = new File([""], "test.mp4", { type: "video/mp4" });
      const promise = validateVideoAspectRatio(file);

      // Trigger metadata but leave dimensions at 0
      (mockVideo as unknown as { videoWidth: number }).videoWidth = 0;
      (mockVideo as unknown as { videoHeight: number }).videoHeight = 0;
      events["loadedmetadata"]();
      events["seeked"]();

      const result = await promise;
      expect(result.thumbnailUrl).toBeNull();
      expect(result.width).toBe(0);
    });

    it("should handle canvas.getContext returning null", async () => {
      mockCanvas.getContext = jest.fn(() => null);

      const file = new File([""], "test.mp4", { type: "video/mp4" });
      const promise = validateVideoAspectRatio(file);

      (mockVideo as unknown as { videoWidth: number }).videoWidth = 1080;
      (mockVideo as unknown as { videoHeight: number }).videoHeight = 1920;
      events["loadedmetadata"]();
      events["seeked"]();

      const result = await promise;
      expect(result.thumbnailUrl).toBeNull();
    });

    it("should handle currentTime setter throwing", async () => {
      Object.defineProperty(mockVideo, "currentTime", {
        set: () => {
          throw new Error("Seek not supported");
        },
        get: () => 0,
      });

      const file = new File([""], "test.mp4", { type: "video/mp4" });
      const promise = validateVideoAspectRatio(file);

      (mockVideo as unknown as { videoWidth: number }).videoWidth = 1080;
      (mockVideo as unknown as { videoHeight: number }).videoHeight = 1920;
      events["loadedmetadata"]();

      const result = await promise;
      expect(result.width).toBe(1080);
    });

    it("should handle video.load throwing", async () => {
      jest.useFakeTimers();
      const consoleSpy = jest
        .spyOn(console, "warn")
        .mockImplementation(() => {});
      mockVideo.load = jest.fn(() => {
        throw new Error("Load failed");
      });

      const file = new File([""], "test.mp4", { type: "video/mp4" });
      const promise = validateVideoAspectRatio(file);

      events["error"]();
      await jest.runOnlyPendingTimersAsync();

      const result = await promise;
      expect(result.thumbnailUrl).toBeNull();
      consoleSpy.mockRestore();
    });

    it("should handle short video duration", async () => {
      (mockVideo as unknown as { duration: number }).duration = 0.5; // Less than 1 second

      const file = new File([""], "test.mp4", { type: "video/mp4" });
      const promise = validateVideoAspectRatio(file);

      (mockVideo as unknown as { videoWidth: number }).videoWidth = 1080;
      (mockVideo as unknown as { videoHeight: number }).videoHeight = 1920;
      events["loadedmetadata"]();
      events["seeked"]();

      const result = await promise;
      expect(result.width).toBe(1080);
    });
  });
});
