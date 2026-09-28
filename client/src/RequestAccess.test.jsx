import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import RequestAccess from "./RequestAccess.jsx";
import { AccessRequests } from "./Admin.jsx";

// Generated per run: no username, email or password is written in this
// repository. ".invalid" is the top-level domain reserved so that no real
// address can exist on it (RFC 2606).
const ID = crypto.randomUUID().slice(0, 8);
const USER = `user-${ID}`;
const EMAIL = `${USER}@${crypto.randomUUID().slice(0, 8)}.invalid`;
const PASSWORD = `Aa1!${crypto.randomUUID()}`;

describe("RequestAccess", () => {
  it("creates the account with the chosen password and puts it on the waitlist", async () => {
    const request = vi.fn(async (b) => ({ status: "pending", username: b.username, role: b.role }));
    render(<MemoryRouter><RequestAccess request={request} /></MemoryRouter>);
    await userEvent.type(screen.getByLabelText("Username"), USER);
    await userEvent.type(screen.getByLabelText("Email"), EMAIL);
    await userEvent.type(screen.getByLabelText("Password"), PASSWORD);
    await userEvent.type(screen.getByLabelText("Confirm password"), PASSWORD);
    await userEvent.selectOptions(screen.getByLabelText(/Role/), "admin");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(request).toHaveBeenCalledWith({ username: USER, email: EMAIL,
                                           password: PASSWORD, role: "admin" });
    expect(await screen.findByTestId("request-sent")).toHaveTextContent(`${USER} is on the waitlist for admin access`);
  });

  it("will not send mismatched passwords", async () => {
    render(<MemoryRouter><RequestAccess request={vi.fn()} /></MemoryRouter>);
    await userEvent.type(screen.getByLabelText("Username"), USER);
    await userEvent.type(screen.getByLabelText("Email"), EMAIL);
    await userEvent.type(screen.getByLabelText("Password"), PASSWORD);
    await userEvent.type(screen.getByLabelText("Confirm password"), "different");
    expect(screen.getByRole("button", { name: "Create account" })).toBeDisabled();
  });
});

describe("AccessRequests", () => {
  it("approves a pending request and shows the new state", async () => {
    let rows = [{ username: USER, email: EMAIL, role: "radiologist", status: "pending",
                  requested_at: "2026-09-28T10:00:00+00:00" }];
    const load = vi.fn(async () => ({ requests: rows }));
    const decide = vi.fn(async (u, d) => { rows = [{ ...rows[0], status: "approved", decided_by: "me" }]; });
    render(<AccessRequests load={load} decide={decide} />);
    await userEvent.click(await screen.findByRole("button", { name: "Approve" }));
    expect(decide).toHaveBeenCalledWith(USER, "approve");
    expect(await screen.findByText("approved by me")).toBeInTheDocument();
  });
});
