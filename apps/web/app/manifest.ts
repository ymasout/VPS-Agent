import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "VPS Agent Console",
    short_name: "VPS Agent",
    description: "可信、受控、可审计的自托管 VPS 运维控制台",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#090b0f",
    theme_color: "#090b0f",
    orientation: "any",
    icons: [
      {
        src: "/pwa-icon.svg",
        sizes: "any",
        type: "image/svg+xml",
        purpose: "any",
      },
      {
        src: "/pwa-icon.svg",
        sizes: "any",
        type: "image/svg+xml",
        purpose: "maskable",
      },
    ],
  };
}
