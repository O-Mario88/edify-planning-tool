import type { MetadataRoute } from "next";

// PWA manifest (spec layer #9) — lets field staff install Edify to the home
// screen and run it standalone, the first step toward an offline-capable field
// app. Pairs with the offline banner + local draft saving.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Edify Planning Tool",
    short_name: "Edify",
    description: "Field planning, SSA, clusters, evidence, and verification for Edify country teams.",
    start_url: "/",
    display: "standalone",
    background_color: "#0b1220",
    theme_color: "#0b1220",
    orientation: "portrait",
    icons: [
      { src: "/favicon.ico", sizes: "any", type: "image/x-icon" },
    ],
  };
}
