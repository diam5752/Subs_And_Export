import {
  buildSubtitleExportFilename,
  withDownloadParameters,
} from "@/lib/exportFilename";

describe("buildSubtitleExportFilename", () => {
  it("keeps the original stem and appends _subs for video and subtitle exports", () => {
    // REGRESSION: downloads used the internal processed_<resolution> filename.
    expect(buildSubtitleExportFilename("E Isous.mp4", "1080x1920")).toBe(
      "E Isous_subs.mp4",
    );
    expect(buildSubtitleExportFilename("συνέντευξη.final.MOV", "srt")).toBe(
      "συνέντευξη.final_subs.srt",
    );
    // REGRESSION: exporting an already suffixed file produced _subs_subs.
    expect(buildSubtitleExportFilename("E Isous_subs.mp4", "vtt")).toBe(
      "E Isous_subs.vtt",
    );
    expect(
      buildSubtitleExportFilename("E Isous_subs_subs.mp4", "1080x1920"),
    ).toBe("E Isous_subs.mp4");
  });

  it("removes path and header-unsafe filename characters with a stable fallback", () => {
    expect(buildSubtitleExportFilename("../folder/bad:name?.mkv", "vtt")).toBe(
      "bad_name__subs.vtt",
    );
    expect(buildSubtitleExportFilename("..", "txt")).toBe("video_subs.txt");
    expect(buildSubtitleExportFilename(null, "2160x3840")).toBe(
      "video_subs.mp4",
    );
    expect(buildSubtitleExportFilename("README", "SRT")).toBe(
      "README_subs.srt",
    );
    expect(buildSubtitleExportFilename("folder\\clip.avi   ", "TXT")).toBe(
      "clip_subs.txt",
    );
  });
});

describe("withDownloadParameters", () => {
  it("adds an encoded filename while preserving existing query parameters and fragments", () => {
    expect(
      withDownloadParameters(
        "/static/video.mp4?token=1#preview",
        "Ε Isous_subs.mp4",
      ),
    ).toBe(
      "/static/video.mp4?token=1&download=true&filename=%CE%95%20Isous_subs.mp4#preview",
    );
  });

  it("adds the first query parameter when no query or fragment exists", () => {
    expect(withDownloadParameters("/static/video.mp4", "video_subs.mp4")).toBe(
      "/static/video.mp4?download=true&filename=video_subs.mp4",
    );
  });
});
