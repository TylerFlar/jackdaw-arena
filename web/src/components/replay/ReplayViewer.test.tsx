import { act, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderAt } from "../../test/server";
import { ReplayViewer } from "./ReplayViewer";

const routes = [{ path: "/", element: <ReplayViewer episodeId="e1" total={4} /> }];

describe("replay viewer", () => {
  it("steps with buttons, keys and the action log", async () => {
    const user = userEvent.setup();
    renderAt("/", routes);
    expect(await screen.findByText("step 0 / 3")).toBeInTheDocument();
    expect((await screen.findByText("Next:")).parentElement).toHaveTextContent("Select Small Blind");
    await user.click(screen.getByRole("button", { name: "Next step" }));
    expect(screen.getByText("step 1 / 3")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "K♠" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(screen.getByText("step 2 / 3")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Home" });
    expect(screen.getByText("step 0 / 3")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Discard K♠/ }));
    expect(screen.getByText("step 2 / 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Discard K♠/ })).toHaveAttribute(
      "aria-current",
      "step",
    );
  });

  it("plays to the end and stops", async () => {
    renderAt("/", routes);
    await screen.findByText("step 0 / 3");
    vi.useFakeTimers();
    try {
      fireEvent.click(screen.getByRole("button", { name: "Play" }));
      for (let k = 0; k < 4; k++) await act(() => vi.advanceTimersByTimeAsync(500));
      expect(screen.getByText("step 3 / 3")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Play" })).toHaveAttribute("aria-pressed", "false");
    } finally {
      vi.useRealTimers();
    }
  });
});
