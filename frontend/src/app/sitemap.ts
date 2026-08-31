import type { MetadataRoute } from "next";

const PRODUCTION_ORIGIN = "https://gsubs.gr";

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    {
      url: `${PRODUCTION_ORIGIN}/`,
      changeFrequency: "weekly",
      priority: 1,
    },
    {
      url: `${PRODUCTION_ORIGIN}/terms`,
      changeFrequency: "yearly",
      priority: 0.3,
    },
    {
      url: `${PRODUCTION_ORIGIN}/privacy`,
      changeFrequency: "yearly",
      priority: 0.3,
    },
  ];
}
