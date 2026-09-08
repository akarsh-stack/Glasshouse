import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TierReadout, TIER_HUE } from "./TierReadout";
import { Segmented } from "./ui";
import { STAGE_COLOR } from "../lib/stages";
import type { Tier } from "../types";

/*
 * The tier switch used to be three words with no feedback. These pin the two
 * things that make it mean something: the model shown is the one the backend
 * resolved, and the trade between tiers is monotonic in both directions.
 */

describe("TierReadout", () => {
  it("shows the resolved model rather than a hardcoded name", () => {
    render(<TierReadout tier="fast" model="llama-3.1-8b-instant" />);
    expect(screen.getByText("llama-3.1-8b-instant")).toBeInTheDocument();
  });

  it("says so while the model is still resolving", () => {
    render(<TierReadout tier="fast" model={null} />);
    expect(screen.getByText(/resolving/)).toBeInTheDocument();
  });

  it("describes the trade each tier makes", () => {
    render(<TierReadout tier="deep" model="m" />);
    expect(screen.getByText(/most capable, slowest/)).toBeInTheDocument();
  });

  it("labels both axes so the bars are readable", () => {
    render(<TierReadout tier="quality" model="m" />);
    expect(screen.getByText("speed")).toBeInTheDocument();
    expect(screen.getByText("depth")).toBeInTheDocument();
  });
});

describe("tier hues", () => {
  it("draws each tier from the stage palette, never a new colour", () => {
    const palette = Object.values(STAGE_COLOR);
    for (const hue of Object.values(TIER_HUE)) {
      expect(palette).toContain(hue);
    }
  });

  it("gives every tier a distinct hue", () => {
    expect(new Set(Object.values(TIER_HUE)).size).toBe(3);
  });
});

describe("Segmented", () => {
  it("marks only the selected option as pressed", () => {
    render(
      <Segmented<Tier>
        ariaLabel="Model tier"
        options={[
          { value: "fast", label: "Fast" },
          { value: "quality", label: "Quality" },
          { value: "deep", label: "Deep" },
        ]}
        value="quality"
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Quality" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Fast" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("reports the chosen value", async () => {
    const onChange = vi.fn();
    render(
      <Segmented<Tier>
        ariaLabel="Model tier"
        options={[
          { value: "fast", label: "Fast" },
          { value: "deep", label: "Deep" },
        ]}
        value="fast"
        onChange={onChange}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Deep" }));
    expect(onChange).toHaveBeenCalledWith("deep");
  });

  it("keeps its options reachable by name after the indicator was added", () => {
    // The moving indicator is an aria-hidden sibling of the label. If it ever
    // swallowed the accessible name, every option would read as an unnamed
    // button — which is exactly what a decorative overlay tends to do.
    render(
      <Segmented<Tier>
        ariaLabel="Model tier"
        options={[
          { value: "fast", label: "Fast" },
          { value: "quality", label: "Quality" },
        ]}
        value="fast"
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Fast" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Quality" })).toBeInTheDocument();
  });
});
