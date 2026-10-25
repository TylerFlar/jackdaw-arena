import { act, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderAt, replayFrames } from "../../test/server";
import { ReplayViewer } from "./ReplayViewer";

const routes = [{ path: "/", element: <ReplayViewer episodeId="e1" /> }];
// The frames: 0 discards, 1 is that discard's outcome, 2 plays a hand, 3 is the end.
const play = replayFrames[2]!;
const outcome = play.outcome!.play!;

afterEach(() => vi.useRealTimers());

describe("replay viewer", () => {
  it("jumps with keys and the action log", async () => {
    const user = userEvent.setup();
    renderAt("/", routes);
    expect(await screen.findByText("step 0 / 3")).toBeInTheDocument();
    expect(screen.getByText("Next:").parentElement).toHaveTextContent(replayFrames[0]!.description!);
    fireEvent.keyDown(window, { key: "ArrowRight", shiftKey: true });
    expect(screen.getByText("step 1 / 3")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "End" });
    expect(screen.getByText("step 3 / 3")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Home" });
    await user.click(screen.getByRole("button", { name: new RegExp(play.description!) }));
    expect(screen.getByText("step 2 / 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: new RegExp(play.description!) })).toHaveAttribute("aria-current", "step");
    // The board: the hand, the jokers, the deck.
    expect(within(screen.getByRole("group", { name: /^Hand / })).getAllByRole("img")).toHaveLength(play.hand.length);
    expect(screen.getByRole("img", { name: `${play.deck_size} cards in the deck` })).toBeInTheDocument();
  });

  it("plays a hand out: into play, each card and joker scoring, then the next frame", async () => {
    renderAt("/", routes);
    await screen.findByText("step 0 / 3");
    fireEvent.keyDown(window, { key: "End" });
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(screen.getByText("step 2 / 3")).toBeInTheDocument();
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "Next step" }));
    const seen = new Set<string>();
    for (let k = 0; k < 60 && !screen.queryByText("step 3 / 3"); k++) {
      await act(() => vi.advanceTimersByTimeAsync(100));
      document.querySelectorAll(".popup").forEach((p) => seen.add(p.textContent ?? ""));
      if (screen.queryByRole("group", { name: "Played cards" })?.querySelector(".board-card")) seen.add("in play");
    }
    expect(screen.getByText("step 3 / 3")).toBeInTheDocument();
    expect(seen).toContain("in play");
    const joker = outcome.events.find((e) => e.kind === "joker")!;
    expect(seen).toContain(`+${joker.mult} Mult`);
  });

  it("plays on to the end and stops", async () => {
    renderAt("/", routes);
    await screen.findByText("step 0 / 3");
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    for (let k = 0; k < 120 && !screen.queryByText("step 3 / 3"); k++) await act(() => vi.advanceTimersByTimeAsync(250));
    expect(screen.getByText("step 3 / 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Play" })).toHaveAttribute("aria-pressed", "false");
  });

  it("shows the old text view on request", async () => {
    const user = userEvent.setup();
    renderAt("/", routes);
    await screen.findByText("step 0 / 3");
    await user.click(screen.getByRole("button", { name: "Text view" }));
    expect(screen.getByText("Phase")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /^Hand / })).toBeNull();
  });
});
