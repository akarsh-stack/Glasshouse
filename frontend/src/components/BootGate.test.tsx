import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BootGate, isLocalOrigin } from "./BootGate";
import { suggestionsFor } from "./SuggestedQuestions";
import type { DocumentInfo } from "../types";

/*
 * The gate exists to replace a silent failure: with the backend down the UI
 * rendered fine and then failed three separate ways (empty rail, errored query,
 * absent metrics). These pin that it holds, that it releases, and that it never
 * traps you.
 */

function mockHealth(impl: () => Promise<Partial<Response>> | never) {
  vi.stubGlobal("fetch", vi.fn(impl));
}

const OK = () =>
  Promise.resolve({ ok: true, json: () => Promise.resolve({ status: "ok" }) } as Response);

beforeEach(() => {
  vi.unstubAllGlobals();
});

describe("BootGate", () => {
  it("renders the app once the backend answers ok", async () => {
    mockHealth(OK);
    render(
      <BootGate>
        <p>app body</p>
      </BootGate>,
    );
    expect(await screen.findByText("app body")).toBeInTheDocument();
  });

  it("holds the app back while the backend is unreachable", async () => {
    mockHealth(() => Promise.reject(new Error("ECONNREFUSED")));
    render(
      <BootGate>
        <p>app body</p>
      </BootGate>,
    );
    await screen.findByText("waiting for backend");
    expect(screen.queryByText("app body")).toBeNull();
  });

  it("treats a 200 that isn't status:ok as not ready", async () => {
    // A dev-server proxy returning its own page still answers 200, which is
    // exactly the case that would otherwise let a broken backend through.
    mockHealth(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ status: "degraded" }),
      } as Response),
    );
    render(
      <BootGate>
        <p>app body</p>
      </BootGate>,
    );
    await screen.findByText("waiting for backend");
    expect(screen.queryByText("app body")).toBeNull();
  });

  it("announces status politely for screen readers", async () => {
    mockHealth(() => Promise.reject(new Error("down")));
    render(
      <BootGate>
        <p>app body</p>
      </BootGate>,
    );
    const status = await screen.findByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
  });

  it("tells a developer how to start the backend, not a visitor", async () => {
    // The hint has to match who is reading it. On a deployed origin, "run
    // uvicorn" is noise; locally, "waking up" hides an unstarted server.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockHealth(() => Promise.reject(new Error("down")));
    render(
      <BootGate>
        <p>app body</p>
      </BootGate>,
    );
    await vi.advanceTimersByTimeAsync(7000);
    expect(await screen.findByText(/uvicorn app.main:app/)).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("offers a way through so the frontend can be inspected offline", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockHealth(() => Promise.reject(new Error("down")));
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(
      <BootGate>
        <p>app body</p>
      </BootGate>,
    );
    await vi.advanceTimersByTimeAsync(7000);
    const escape = await screen.findByRole("button", {
      name: /continue without a backend/i,
    });
    await user.click(escape);
    await waitFor(() => expect(screen.getByText("app body")).toBeInTheDocument());
    vi.useRealTimers();
  });
});

/* ---------------------------------------------------------- suggestions */

const doc = (filename: string): DocumentInfo =>
  ({ id: filename, filename, chunk_count: 1, status: "ready" }) as DocumentInfo;

describe("suggestionsFor", () => {
  it("offers nothing when no documents are loaded", () => {
    expect(suggestionsFor([])).toEqual([]);
    expect(suggestionsFor(null)).toEqual([]);
  });

  it("tailors questions to the sample corpus when it is present", () => {
    const s = suggestionsFor([doc("orbital-mechanics-notes.md")]);
    expect(s.some((q) => /life support/i.test(q.text))).toBe(true);
  });

  it("includes the cache-demo pair, which is the best 60s of the demo", () => {
    const s = suggestionsFor([doc("orbital-mechanics-notes.md")]);
    const texts = s.map((q) => q.text);
    expect(texts).toContain("How much water does life support recycle?");
    expect(texts).toContain("What percentage of water does life support recycle?");
  });

  it("falls back to generic openers for an unknown corpus", () => {
    const s = suggestionsFor([doc("q3-invoices.pdf")]);
    expect(s.length).toBeGreaterThan(0);
    // A suggestion naming a document the user never uploaded is worse than none.
    expect(s.every((q) => !/life support|incremental linking/i.test(q.text))).toBe(true);
  });

  it("never offers more than four", () => {
    const s = suggestionsFor([
      doc("orbital-mechanics-notes.md"),
      doc("meridian-release-notes.pdf"),
    ]);
    expect(s.length).toBeLessThanOrEqual(4);
  });
});

describe("isLocalOrigin", () => {
  it("recognises development hosts", () => {
    for (const h of ["localhost", "127.0.0.1", "[::1]", "mymac.local", ""]) {
      expect(isLocalOrigin(h)).toBe(true);
    }
  });

  it("treats a deployed origin as remote", () => {
    for (const h of ["glasshouse.onrender.com", "glasshouse.vercel.app", "example.com"]) {
      expect(isLocalOrigin(h)).toBe(false);
    }
  });

  it("does not mistake a hostname merely containing localhost", () => {
    expect(isLocalOrigin("notlocalhost.com")).toBe(false);
  });
});
