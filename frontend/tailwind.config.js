/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // Palette v2. The first pass read as one flat blue-grey wash, and the
      // measurements said why: mean accent chroma 29%, three of the four stage
      // hues within 0.035 luminance of each other, and only 0.028 luminance
      // separating four surface tokens. "Restrained" had become inert.
      //
      // Two changes. Accents go to ~62% mean chroma — on a ground this dark
      // that reads as *emissive*, a lit instrument rather than loud paint. And
      // the four stage hues now sit on a deliberate luminance ladder
      // (0.341 / 0.445 / 0.544 / 0.604) so they can be ranked by brightness
      // alone, which also means the pipeline survives colour-blindness.
      colors: {
        ink: {
          950: "#080D1A", // app background
          900: "#101A2E", // panel
          800: "#1C2947", // raised surface, card
          700: "#33456F", // border, divider
          600: "#4A5F94", // emphasis border, hover edge
          300: "#94A6CC", // secondary text — 7.1:1 on ink-900
          100: "#E4EBFA", // primary text — 14.5:1 on ink-900
        },
        stage: {
          embed: "#3DDC97", // spring green   lum 0.544
          cache: "#FFC24D", // gold           lum 0.604
          retrieve: "#A98BFF", // violet      lum 0.341
          generate: "#3FBEF5", // sky         lum 0.445
        },
        warn: "#FF7A66", // coral            lum 0.361
      },
      fontFamily: {
        display: ['"Space Grotesk"', "system-ui", "sans-serif"],
        body: ['"Instrument Sans"', "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      // A named scale, added alongside Tailwind's defaults rather than
      // replacing them. Sizes were previously ad-hoc — 10, 10.5, 11, 12, 13, 15,
      // 17 and 30px all appeared, so nothing sat in a clear relationship to
      // anything else and the whole interface read at one volume.
      //
      // Each step is a *role*, not a size, so call sites say what a thing is.
      fontSize: {
        label: ["11px", { lineHeight: "1", letterSpacing: "0.14em" }],
        meta: ["12px", { lineHeight: "1.5" }],
        ui: ["14px", { lineHeight: "1.5" }],
        // The answer. It is the product's output and was set at 15px, barely
        // above a caption; 17/1.7 is the first thing on screen that reads as
        // something to sit and read.
        lede: ["17px", { lineHeight: "1.7" }],
        title: ["20px", { lineHeight: "1.25", letterSpacing: "-0.012em" }],
        readout: ["34px", { lineHeight: "1", letterSpacing: "-0.022em" }],
      },
      maxWidth: {
        // ~68 characters at 17px. Anything wider and the eye loses the line
        // return on a 1440px display, which is why the answer felt like a wall.
        measure: "62ch",
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
