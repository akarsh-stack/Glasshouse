/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    // jsdom only for files that render components; the pure-logic suites
    // (stageTimeline) don't need a DOM and run faster without one, but a single
    // environment keeps the config honest and the difference is milliseconds.
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    globals: false,
  },
  server: {
    // Pinned rather than left on Vite's 5173 default. 5173 is the default for
    // every Vite project, so on a machine running more than one the server
    // silently lands on 5174, 5175, … and the URL changes between runs.
    // strictPort turns that into a loud failure instead: if 5180 is taken you
    // find out immediately rather than by wondering why your edits aren't
    // showing up in the tab you had open.
    port: 5190,
    strictPort: true,
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
