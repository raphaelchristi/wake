// Tailwind v4 is CSS-first; this file is included only for editor tooling
// that still expects a JS/TS config. The real theme lives in
// src/app/globals.css and src/styles/tokens.css.
import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/**/*.{ts,tsx}",
  ],
  darkMode: "class",
};

export default config;
