/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0B1120",
          900: "#111A2E",
          800: "#1A2540",
          700: "#263354",
          300: "#8B99B8",
          100: "#DDE4F2",
        },
        stage: {
          embed: "#7C9E8F",
          retrieve: "#9287C0",
          cache: "#C7A96B",
          generate: "#6B95C7",
        },
        warn: "#C77B6B",
      },
      fontFamily: {
        display: ['"Space Grotesk"', "system-ui", "sans-serif"],
        body: ['"Instrument Sans"', "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      // Depth scale. Three stacked layers per level rather than one blur: a
      // tight contact shadow that anchors the element to the surface below, a
      // mid diffuse layer, and a wide ambient one. A single shadow on a dark
      // background reads as a grey smudge; the tight layer is what actually
      // sells the lift, because it's the only one the eye reads as contact.
      //
      // Opacities run high (0.5-0.66) because the base is #0B1120 — a shadow
      // barely darker than the panel it sits on is invisible. These are tuned
      // against that base, not against white.
      // 120ms sits between Tailwind's 100 and 150 steps: fast enough to read as
      // a direct response to the cursor, slow enough that the shadow growth is
      // perceptible rather than a jump.
      transitionDuration: { 120: "120ms" },
      boxShadow: {
        panel:
          "0 1px 1px rgba(3,7,18,0.5), 0 2px 6px -2px rgba(3,7,18,0.45), 0 8px 20px -8px rgba(3,7,18,0.5)",
        raised:
          "0 1px 2px rgba(3,7,18,0.55), 0 4px 10px -3px rgba(3,7,18,0.5), 0 14px 32px -12px rgba(3,7,18,0.6)",
        lift: "0 2px 4px rgba(3,7,18,0.55), 0 8px 18px -4px rgba(3,7,18,0.55), 0 22px 48px -16px rgba(3,7,18,0.66)",
      },
    },
  },
  plugins: [],
};
