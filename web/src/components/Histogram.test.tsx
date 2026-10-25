import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Histogram } from "./Histogram";

describe("histogram", () => {
  it("shows a tooltip on focus and has a table view", async () => {
    render(<Histogram counts={[3, 0, 5]} title="Episodes by blinds beaten" />);
    fireEvent.focus(screen.getByLabelText("5 episodes beat 2 blinds"));
    expect(screen.getByRole("status")).toHaveTextContent("5 episodes · 2 blinds beaten");
    await userEvent.click(screen.getByRole("button", { name: "Show table" }));
    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(rows.map((r) => [...r.querySelectorAll("td")].map((c) => c.textContent))).toEqual([
      ["0", "3", "37.5%"],
      ["1", "0", "0.0%"],
      ["2", "5", "62.5%"],
    ]);
  });

  it("says so when there's nothing to show", () => {
    render(<Histogram counts={[]} title="x" />);
    expect(screen.getByText("No ended episodes yet.")).toBeInTheDocument();
  });
});
