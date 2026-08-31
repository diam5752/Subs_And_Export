import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

import { BrandLogo } from "@/components/BrandLogo";

describe("BrandLogo", () => {
  it("renders the canonical stacked gsubs logo by default", () => {
    // REGRESSION: The stacked waveform-to-subtitles logo was replaced by a
    // horizontal compact-split pill that the owner had not selected.
    render(<BrandLogo className="brand-test" />);

    const logo = screen.getByRole("img", { name: "gsubs" });
    expect(logo).toHaveAttribute("src", "/brand/gsubs-logo.svg");
    expect(logo).toHaveAttribute("width", "280");
    expect(logo).toHaveAttribute("height", "208");
    expect(logo).toHaveClass("brand-test");
  });

  it("supports the matching waveform-to-subtitles mark asset", () => {
    render(<BrandLogo markOnly />);
    expect(screen.getByRole("img", { name: "gsubs" })).toHaveAttribute(
      "src",
      "/brand/gsubs-mark.svg",
    );
    expect(screen.getByRole("img", { name: "gsubs" })).toHaveAttribute(
      "width",
      "256",
    );
    expect(screen.getByRole("img", { name: "gsubs" })).toHaveAttribute(
      "height",
      "256",
    );
  });
});
