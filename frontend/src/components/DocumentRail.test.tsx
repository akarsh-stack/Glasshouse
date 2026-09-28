import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DocumentRail } from "./DocumentRail";
import { uploadsPersist } from "../lib/origin";
import type { DocumentInfo } from "../types";

/*
 * The deployed free instance keeps its Chroma directory and trace DB on
 * ephemeral storage and spins down when idle, so an upload silently vanishes on
 * the next wake. That happened in practice: a resume uploaded, queried, and then
 * gone twenty minutes later with nothing on screen to explain it.
 *
 * Saying so is the honest fix. Saying so *locally*, where the same path is a
 * real directory that persists, would be a lie — hence the origin check.
 */

const docs: DocumentInfo[] = [
  { id: "1", filename: "notes.md", chunk_count: 6, status: "ready" } as DocumentInfo,
];

function renderRail(overrides = {}) {
  return render(
    <DocumentRail
      documents={docs}
      error={null}
      uploads={[]}
      onUpload={vi.fn()}
      onDelete={vi.fn()}
      {...overrides}
    />,
  );
}

const NOTICE = /uploads reset|reset when|don't survive|do not survive/i;

describe("ephemeral-storage notice", () => {
  it("warns when uploads will not survive a restart", () => {
    renderRail({ uploadsPersist: false });
    expect(screen.getByText(NOTICE)).toBeInTheDocument();
  });

  it("stays quiet when storage is durable", () => {
    renderRail({ uploadsPersist: true });
    expect(screen.queryByText(NOTICE)).toBeNull();
  });

  it("does not shout — it is a caveat, not an error", () => {
    renderRail({ uploadsPersist: false });
    // An alert role would interrupt a screen reader for something that is
    // merely context about the hosting tier.
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("still shows the documents alongside it", () => {
    renderRail({ uploadsPersist: false });
    expect(screen.getByText("notes.md")).toBeInTheDocument();
  });
});

describe("uploadsPersist", () => {
  it("treats development hosts as durable", () => {
    for (const h of ["localhost", "127.0.0.1", "[::1]", "mymac.local"]) {
      expect(uploadsPersist(h)).toBe(true);
    }
  });

  it("treats a deployed origin as ephemeral", () => {
    for (const h of ["glasshouse-tbm3.onrender.com", "example.com"]) {
      expect(uploadsPersist(h)).toBe(false);
    }
  });
});
