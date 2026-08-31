import {
  describeResolution,
  describeResolutionString,
  parseResolutionString,
} from "../video";

describe("video resolution descriptions", () => {
  describe("parseResolutionString", () => {
    it("should parse valid resolution strings", () => {
      expect(parseResolutionString("1920x1080")).toEqual({
        width: 1920,
        height: 1080,
      });
      expect(parseResolutionString("1280X720")).toEqual({
        width: 1280,
        height: 720,
      });
      expect(parseResolutionString(" 1080 x 1920 ")).toEqual({
        width: 1080,
        height: 1920,
      });
      expect(parseResolutionString("1080×1920")).toEqual({
        width: 1080,
        height: 1920,
      });
    });

    it("should return null for invalid strings", () => {
      expect(parseResolutionString("")).toBeNull();
      expect(parseResolutionString(null)).toBeNull();
      expect(parseResolutionString(undefined)).toBeNull();
      expect(parseResolutionString("invalid")).toBeNull();
      expect(parseResolutionString("100x")).toBeNull();
    });
  });

  describe("describeResolution", () => {
    it("should describe standard resolutions correctly", () => {
      expect(describeResolution(3840, 2160)).toEqual({
        text: "3840×2160",
        label: "4K / 2160p",
      });
      expect(describeResolution(2560, 1440)).toEqual({
        text: "2560×1440",
        label: "QHD / 1440p",
      });
      expect(describeResolution(1920, 1080)).toEqual({
        text: "1920×1080",
        label: "Full HD / 1080p",
      });
      expect(describeResolution(1280, 720)).toEqual({
        text: "1280×720",
        label: "HD / 720p",
      });
      expect(describeResolution(640, 480)).toEqual({
        text: "640×480",
        label: "SD",
      });
    });

    it("should return null for invalid dimensions", () => {
      expect(describeResolution(0, 100)).toBeNull();
      expect(describeResolution(100, 0)).toBeNull();
      expect(describeResolution(undefined, 100)).toBeNull();
      expect(describeResolution(100, undefined)).toBeNull();
    });
  });

  describe("describeResolutionString", () => {
    it("should describe valid resolution strings", () => {
      expect(describeResolutionString("1920x1080")).toEqual({
        text: "1920×1080",
        label: "Full HD / 1080p",
      });
      expect(describeResolutionString("1080x1920")).toEqual({
        text: "1080×1920",
        label: "Full HD / 1080p",
      });
    });

    it("should return null for invalid strings", () => {
      expect(describeResolutionString("")).toBeNull();
      expect(describeResolutionString(null)).toBeNull();
      expect(describeResolutionString("invalid")).toBeNull();
    });
  });
});
