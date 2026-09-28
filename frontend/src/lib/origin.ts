/**
 * Is the page served from a dev machine rather than a deployed origin?
 *
 * Two things branch on this, and both would be wrong if they guessed:
 * the boot screen's hint (telling a visitor to run `uvicorn` is noise), and
 * the document rail's warning that uploads don't survive a restart — which is
 * true on a free host with no persistent disk, and false locally where the
 * Chroma directory is a real folder on a real disk.
 */
export function isLocalOrigin(hostname: string): boolean {
  return (
    hostname === "localhost" ||
    hostname === "127.0.0.1" ||
    hostname === "[::1]" ||
    hostname === "" ||
    hostname.endsWith(".local")
  );
}

/**
 * Whether uploaded documents survive a restart.
 *
 * A deployed free-tier instance keeps `/data` on ephemeral storage and spins
 * down when idle, so an upload silently disappears — the worst kind of failure,
 * because nothing tells you it happened. Locally the same path is a real
 * directory that persists.
 */
export function uploadsPersist(hostname: string = window.location.hostname): boolean {
  return isLocalOrigin(hostname);
}
