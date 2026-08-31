import React from "react";
import fs from "fs";
import path from "path";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

import manifest from "@/app/manifest";
import OfflinePage from "@/app/offline/page";
import robots from "@/app/robots";
import sitemap from "@/app/sitemap";

describe("static application routes", () => {
  it("publishes installable gsubs metadata", () => {
    expect(manifest()).toEqual(
      expect.objectContaining({
        name: "gsubs · Subtitle Studio",
        short_name: "gsubs",
        start_url: "/",
        display: "standalone",
        lang: "el",
      }),
    );
    expect(manifest().icons).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ src: "/icon.png", sizes: "1024x1024" }),
      ]),
    );
  });

  it("offers a working recovery route while offline", () => {
    render(<OfflinePage />);

    expect(screen.getByText("GSUBS / OFFLINE")).toBeInTheDocument();
    expect(screen.getByRole("heading")).toHaveTextContent(
      "Δεν υπάρχει σύνδεση",
    );
    expect(screen.getByRole("link", { name: "Δοκιμή ξανά" })).toHaveAttribute(
      "href",
      "/",
    );
  });

  it("publishes only public pages for production search discovery", () => {
    expect(robots()).toEqual({
      rules: {
        userAgent: "*",
        allow: "/",
        disallow: ["/account/", "/admin/", "/login", "/offline", "/register"],
      },
      sitemap: "https://gsubs.gr/sitemap.xml",
      host: "https://gsubs.gr",
    });
    expect(sitemap()).toEqual([
      {
        url: "https://gsubs.gr/",
        changeFrequency: "weekly",
        priority: 1,
      },
      {
        url: "https://gsubs.gr/terms",
        changeFrequency: "yearly",
        priority: 0.3,
      },
      {
        url: "https://gsubs.gr/privacy",
        changeFrequency: "yearly",
        priority: 0.3,
      },
    ]);
  });

  it("ships the production logo, mark, icon and watermark assets", () => {
    const publicRoot = path.join(process.cwd(), "public");
    const assetPaths = [
      "brand/gsubs-logo.svg",
      "brand/gsubs-mark.svg",
      "brand/gsubs-social-card.svg",
      "brand/gsubs-social-card.png",
      "brand/gsubs-watermark.svg",
      "gsubs-watermark.png",
      "icon.png",
    ];

    for (const assetPath of assetPaths) {
      expect(
        fs.statSync(path.join(publicRoot, assetPath)).size,
      ).toBeGreaterThan(0);
    }
    for (const retiredAssetPath of [
      "brand/gsubs-logo-light.svg",
      "brand/gsubs-logo-dark.svg",
      "brand/gsubs-logo-stacked-light.svg",
      "brand/gsubs-logo-stacked-dark.svg",
    ]) {
      expect(fs.existsSync(path.join(publicRoot, retiredAssetPath))).toBe(
        false,
      );
    }

    const canonicalLogo = fs.readFileSync(
      path.join(publicRoot, "brand/gsubs-logo.svg"),
      "utf8",
    );
    // REGRESSION: The owner-selected stacked logo was replaced by a
    // horizontal compact-split pill.
    expect(canonicalLogo).toContain(
      "Audio waveform becoming subtitle lines above the gsubs wordmark",
    );
    expect(canonicalLogo).toContain('data-brand-mark="waveform-to-subtitles"');
    expect(canonicalLogo).toContain('viewBox="0 0 280 208"');
    expect(canonicalLogo).toContain("#166095");
    expect(canonicalLogo).toContain("#c66a21");
    expect(canonicalLogo).toContain("M160 36L178 52L160 68");
    expect(canonicalLogo).not.toContain('data-brand-mark="compact-split"');

    const socialCard = fs.readFileSync(
      path.join(publicRoot, "brand/gsubs-social-card.png"),
    );
    // REGRESSION: Without an explicit 1200x630 share image, link previews
    // enlarged the square app icon and cropped the gsubs logo.
    expect(socialCard.subarray(0, 8)).toEqual(
      Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    );
    expect(socialCard.readUInt32BE(16)).toBe(1200);
    expect(socialCard.readUInt32BE(20)).toBe(630);
  });
});
