import { fmtNum } from "../lib/format";
import { STAGE_COLOR } from "../lib/stages";
import type { CacheStatus } from "../types";
import { Badge } from "./ui";

interface CacheBadgeProps {
  status: CacheStatus;
  similarity: number | null;
  /** Model in play on a miss (known once the trace arrives) */
  model?: string;
}

/* A filled dot in the badge hue. The cache verdict is the single most-glanced
   fact in the demo, and a leading dot is recognisable at a distance where the
   text is not — you can see which way it went before you read it. */
function Dot({ color }: { color: string }) {
  return (
    <span
      aria-hidden
      className="inline-block h-1.5 w-1.5 shrink-0 rounded-full"
      style={{ backgroundColor: color, boxShadow: `0 0 6px ${color}` }}
    />
  );
}

export function CacheBadge({ status, similarity, model }: CacheBadgeProps) {
  if (status === "miss") {
    return (
      <Badge color={STAGE_COLOR.generate}>
        <Dot color={STAGE_COLOR.generate} />
        Cache miss → calling{" "}
        <span className="font-mono text-label font-medium">{model || "model"}</span>
      </Badge>
    );
  }
  const kind = status === "hit_exact" ? "exact" : "semantic";
  return (
    <Badge color={STAGE_COLOR.cache}>
      <Dot color={STAGE_COLOR.cache} />
      Cache hit — {kind}
      {status === "hit_semantic" && similarity !== null && (
        <>
          ,{" "}
          <span className="font-mono text-label font-medium tabular-nums">
            {fmtNum(similarity, 2)}
          </span>{" "}
          similarity
        </>
      )}
    </Badge>
  );
}
