import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Answer } from "./Answer";

/*
 * The citation link is the product's central claim made operable — "you can see
 * where the answer came from" is weaker if checking it means matching numbers
 * across two panels by eye. It shipped with no coverage at all.
 */

function setup(overrides: Partial<Parameters<typeof Answer>[0]> = {}) {
  const onCitationHover = vi.fn();
  const onCitationSelect = vi.fn();
  render(
    <Answer
      text="Water recovery runs at 93 percent[1]. Power is 84 kilowatts[2]."
      streaming={false}
      citationCount={2}
      activeCitation={null}
      onCitationHover={onCitationHover}
      onCitationSelect={onCitationSelect}
      {...overrides}
    />,
  );
  return { onCitationHover, onCitationSelect };
}

describe("citations", () => {
  it("renders each [n] as its own control", () => {
    setup();
    expect(screen.getByRole("button", { name: "Show source 1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show source 2" })).toBeInTheDocument();
  });

  it("keeps the surrounding prose intact", () => {
    setup();
    expect(screen.getByText(/Water recovery runs at 93 percent/)).toBeInTheDocument();
  });

  it("reports the citation on hover", async () => {
    const { onCitationHover } = setup();
    await userEvent.hover(screen.getByRole("button", { name: "Show source 2" }));
    expect(onCitationHover).toHaveBeenCalledWith(2);
  });

  it("clears the highlight on unhover", async () => {
    const { onCitationHover } = setup();
    const cite = screen.getByRole("button", { name: "Show source 1" });
    await userEvent.hover(cite);
    await userEvent.unhover(cite);
    expect(onCitationHover).toHaveBeenLastCalledWith(null);
  });

  it("selects on click", async () => {
    const { onCitationSelect } = setup();
    await userEvent.click(screen.getByRole("button", { name: "Show source 1" }));
    expect(onCitationSelect).toHaveBeenCalledWith(1);
  });

  it("is reachable by keyboard", async () => {
    const { onCitationHover } = setup();
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Show source 1" })).toHaveFocus();
    // Focus drives the same highlight as hover, so keyboard users get the link.
    expect(onCitationHover).toHaveBeenCalledWith(1);
  });
});

describe("out-of-range citations", () => {
  it("leaves [n] beyond the chunk count as plain text", () => {
    setup({ text: "Claim[7].", citationCount: 2 });
    expect(screen.queryByRole("button", { name: "Show source 7" })).toBeNull();
    expect(screen.getByText(/Claim\[7\]\./)).toBeInTheDocument();
  });

  it("renders nothing as a control when there are no chunks", () => {
    setup({ text: "Answer with no context[1].", citationCount: 0 });
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("streaming", () => {
  it("shows a caret while tokens are still arriving", () => {
    const { container } = render(
      <Answer
        text="Partial"
        streaming
        citationCount={0}
        activeCitation={null}
        onCitationHover={vi.fn()}
        onCitationSelect={vi.fn()}
      />,
    );
    expect(container.querySelector(".answer-caret")).toBeTruthy();
  });

  it("drops the caret once the stream finishes", () => {
    const { container } = render(
      <Answer
        text="Complete."
        streaming={false}
        citationCount={0}
        activeCitation={null}
        onCitationHover={vi.fn()}
        onCitationSelect={vi.fn()}
      />,
    );
    expect(container.querySelector(".answer-caret")).toBeNull();
  });
});
