import type { MetadataRoute } from "next";
import { BRAND } from "@/lib/brand";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: BRAND.productTitle,
    short_name: BRAND.name,
    description: BRAND.description,
    start_url: "/",
    display: "standalone",
    background_color: "#08090c",
    theme_color: "#08090c",
    orientation: "any",
    lang: "el",
    categories: ["video", "productivity", "utilities"],
    icons: [
      {
        src: BRAND.assets.icon,
        sizes: "1024x1024",
        type: "image/png",
        purpose: "any",
      },
      {
        src: BRAND.assets.icon,
        sizes: "1024x1024",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
