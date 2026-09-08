import { memo } from "react";
import { useReducedMotion } from "../hooks/useReducedMotion";
import { INK, STAGES } from "../lib/stages";

/*
 * The logo, given depth.
 *
 * The mark says "one signal enters glass and leaves as four". Here the glass is
 * an actual slab — six translucent faces in CSS 3D — rotating slowly while the
 * beams stay fixed in the plane of the screen. Light passing through turning
 * glass, which is the same idea the flat mark states, only now you can see the
 * thing it passes through.
 *
 * Built with CSS 3D transforms rather than WebGL on purpose. three.js is around
 * 150 KB gzipped against a bundle that is currently 92 KB — roughly tripling
 * first load to decorate a screen most people see for under two seconds. Every
 * face here is a div the compositor already knows how to draw.
 *
 * Beams are deliberately *outside* the rotating rig. Inside it they foreshorten
 * to nothing every half turn, which reads as a rendering fault rather than a
 * rotation.
 */

const W = 62; // slab width
const H = 132; // slab height
const D = 30; // slab depth

const FACES: { transform: string; w: number; h: number }[] = [
  { transform: `translateZ(${D / 2}px)`, w: W, h: H }, // front
  { transform: `rotateY(180deg) translateZ(${D / 2}px)`, w: W, h: H }, // back
  { transform: `rotateY(90deg) translateZ(${W / 2}px)`, w: D, h: H }, // right
  { transform: `rotateY(-90deg) translateZ(${W / 2}px)`, w: D, h: H }, // left
  { transform: `rotateX(90deg) translateZ(${H / 2}px)`, w: W, h: D }, // top
  { transform: `rotateX(-90deg) translateZ(${H / 2}px)`, w: W, h: D }, // bottom
];

/** Same fan as the mark: ±28° and ±9.5°, equal length. */
const ORIGIN = { x: 100, y: 100 };
const BEAM_LEN = 88;
const BEAMS = [-28, -9.5, 9.5, 28].map((deg) => {
  const rad = (deg * Math.PI) / 180;
  return {
    x: ORIGIN.x + Math.cos(rad) * BEAM_LEN,
    y: ORIGIN.y + Math.sin(rad) * BEAM_LEN,
  };
});

export const Glasshouse3D = memo(function Glasshouse3D({ size = 200 }: { size?: number }) {
  const reducedMotion = useReducedMotion();

  return (
    <div
      className="relative grid place-items-center"
      style={{ width: size, height: size }}
      aria-hidden
    >
      {/* Pool of light the slab sits in — the same ambient treatment the hero
          trace uses, so the boot screen and the app share one vocabulary. */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(46% 46% at 50% 50%, rgba(63,190,245,0.16) 0%, rgba(169,139,255,0.08) 45%, transparent 72%)",
        }}
      />

      {/* 3D layer */}
      <div
        className="absolute inset-0 grid place-items-center"
        style={{ perspective: "620px" }}
      >
        <div
          className={reducedMotion ? "gh3d-rig-static" : "gh3d-rig"}
          style={{ width: W, height: H, transformStyle: "preserve-3d" }}
        >
          {FACES.map((f, i) => (
            <div
              key={i}
              className="absolute"
              style={{
                width: f.w,
                height: f.h,
                left: "50%",
                top: "50%",
                marginLeft: -f.w / 2,
                marginTop: -f.h / 2,
                transform: f.transform,
                // Glass: barely-there fill, a visible edge, and an inner
                // highlight along the top. The edge is what sells it — a
                // translucent quad with no rim reads as fog, not a pane.
                background:
                  "linear-gradient(160deg, rgba(63,190,245,0.10), rgba(169,139,255,0.05) 55%, rgba(228,235,250,0.02))",
                border: `1px solid ${INK[100]}22`,
                boxShadow: `inset 0 1px 0 0 ${INK[100]}1f`,
                backfaceVisibility: "visible",
              }}
            />
          ))}
        </div>
      </div>

      {/* 2D beam layer, fixed in the screen plane */}
      <svg
        viewBox="0 0 200 200"
        className="absolute inset-0 h-full w-full"
        fill="none"
      >
        <path
          d={`M14 ${ORIGIN.y}H${ORIGIN.x}`}
          stroke={INK[100]}
          strokeWidth="3"
          strokeLinecap="round"
          className={reducedMotion ? undefined : "gh3d-in"}
        />
        {STAGES.map((stage, i) => (
          <path
            key={stage.key}
            d={`M${ORIGIN.x} ${ORIGIN.y}L${BEAMS[i].x.toFixed(1)} ${BEAMS[i].y.toFixed(1)}`}
            stroke={stage.color}
            strokeWidth="3"
            strokeLinecap="round"
            style={{
              filter: `drop-shadow(0 0 5px ${stage.color}88)`,
              // Staggered pulse: the same 40ms rhythm as every other
              // sequenced element in the app.
              animationDelay: `${i * 0.14}s`,
            }}
            className={reducedMotion ? undefined : "gh3d-beam"}
          />
        ))}
      </svg>
    </div>
  );
});
