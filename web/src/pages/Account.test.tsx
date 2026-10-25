import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { me, renderAt, server, url } from "../test/server";
import { AccountPage } from "./Account";

const routes = [{ path: "/me", element: <AccountPage /> }];

describe("account", () => {
  it("asks you to sign in", async () => {
    renderAt("/me", routes);
    const link = await screen.findByRole("link", { name: "Sign in with GitHub" });
    expect(link).toHaveAttribute("href", "/auth/login/github?next=%2Fme");
  });

  it("shows a new token once and sends the CSRF header", async () => {
    const seen: Headers[] = [];
    server.use(
      http.get(url("/auth/session"), () => HttpResponse.json({ user: me.user })),
      http.get(url("/api/me"), () => HttpResponse.json(me)),
      http.post(url("/api/me/agents/:slug/tokens"), async ({ request }) => {
        seen.push(request.headers);
        const body = (await request.json()) as { label: string };
        return HttpResponse.json(
          { id: "t-2", token: "jdk_SECRET_shown_once", prefix: "jdk_SECRET", label: body.label },
          { status: 201 },
        );
      }),
      http.delete(url("/api/me/tokens/:id"), ({ request }) => {
        seen.push(request.headers);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderAt("/me", routes);
    const card = await screen.findByRole("region", { name: "PPO-DEMO" });
    expect(within(card).getByText("jdk_abc123…")).toBeInTheDocument();
    await user.type(within(card).getByLabelText("Token label"), "cluster");
    await user.click(within(card).getByRole("button", { name: "New token" }));
    expect(await screen.findByTestId("new-token")).toHaveTextContent("jdk_SECRET_shown_once");
    expect(seen[0]!.get("x-arena-csrf")).toBe("1");
    await user.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByTestId("new-token")).not.toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(seen).toHaveLength(2));
    expect(seen[1]!.get("x-arena-csrf")).toBe("1");
  });
});
