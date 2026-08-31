import {
  ATHENS_TIME_ZONE,
  currentEpochSeconds,
  currentMinuteEpochSeconds,
  isCanonicalAadeMark,
  isSupportedAadeSeries,
  parseAthensDateTime,
  toAthensDateTimeValue,
} from "@/lib/billingAdmin";

describe("billing admin presentation helpers", () => {
  it("derives deterministic current second and minute values", () => {
    const dateNow = jest
      .spyOn(Date, "now")
      .mockReturnValue(Date.parse("2026-07-26T07:08:09.987Z"));

    expect(currentEpochSeconds()).toBe(
      Date.parse("2026-07-26T07:08:09Z") / 1000,
    );
    expect(currentMinuteEpochSeconds()).toBe(
      Date.parse("2026-07-26T07:08:00Z") / 1000,
    );

    dateNow.mockRestore();
  });

  it.each(["0", "A-1", "ΠΑΡ/1", "ΣΕΙΡΑ_2.0"])(
    "accepts an AADE-compatible series: %s",
    (series) => {
      expect(isSupportedAadeSeries(series)).toBe(true);
    },
  );

  it.each(["", "   ", "SERIES 1", "A#1"])(
    "rejects an unsupported AADE series: %s",
    (series) => {
      expect(isSupportedAadeSeries(series)).toBe(false);
    },
  );

  it.each(["1", "400014466064287", "9223372036854775807"])(
    "accepts a canonical xs:long-compatible MARK: %s",
    (mark) => {
      expect(isCanonicalAadeMark(mark)).toBe(true);
    },
  );

  it.each(["0", "01", "9223372036854775808", "12345678901234567890", "MARK-1"])(
    "rejects a non-canonical MARK: %s",
    (mark) => {
      expect(isCanonicalAadeMark(mark)).toBe(false);
    },
  );

  it("round-trips winter and summer Europe/Athens date-time values", () => {
    expect(ATHENS_TIME_ZONE).toBe("Europe/Athens");
    expect(parseAthensDateTime("2026-01-15T14:30")).toBe(
      Date.parse("2026-01-15T12:30:00Z") / 1000,
    );
    expect(parseAthensDateTime("2026-07-15T14:30")).toBe(
      Date.parse("2026-07-15T11:30:00Z") / 1000,
    );
    expect(
      toAthensDateTimeValue(Date.parse("2026-07-15T11:30:00Z") / 1000),
    ).toBe("2026-07-15T14:30");
  });

  it("fails closed for invalid, nonexistent, or ambiguous Athens minutes", () => {
    expect(parseAthensDateTime("not-a-date")).toBeNull();
    expect(parseAthensDateTime("2026-02-30T12:00")).toBeNull();
    expect(parseAthensDateTime("2026-03-29T03:30")).toBeNull();
    expect(parseAthensDateTime("2026-10-25T03:30")).toBeNull();
  });
});
