import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import Login from "./Login.jsx";
import { api } from "./api.js";

describe("Login", () => {
  it("renders the demo credentials box and eye toggle icon", () => {
    render(<MemoryRouter><Login onLogin={vi.fn()} /></MemoryRouter>);
    expect(screen.getByText("Login using demo credentials")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Login using demo credentials/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show password" })).toBeInTheDocument();
  });

  it("autofills radiologist and <NewPassword1!> when demo credentials box is clicked", async () => {
    render(<MemoryRouter><Login onLogin={vi.fn()} /></MemoryRouter>);
    const userInput = screen.getByLabelText("User");
    const passwordInput = screen.getByLabelText("Password");

    expect(userInput).toHaveValue("");
    expect(passwordInput).toHaveValue("");

    await userEvent.click(screen.getByText("Login using demo credentials"));

    expect(userInput).toHaveValue("radiologist");
    expect(passwordInput).toHaveValue("<NewPassword1!>");
  });

  it("toggles password visibility when the eye icon is clicked", async () => {
    render(<MemoryRouter><Login onLogin={vi.fn()} /></MemoryRouter>);
    const passwordInput = screen.getByLabelText("Password");
    const toggleBtn = screen.getByRole("button", { name: "Show password" });

    expect(passwordInput).toHaveAttribute("type", "password");

    await userEvent.click(toggleBtn);
    expect(passwordInput).toHaveAttribute("type", "text");
    expect(screen.getByRole("button", { name: "Hide password" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Hide password" }));
    expect(passwordInput).toHaveAttribute("type", "password");
    expect(screen.getByRole("button", { name: "Show password" })).toBeInTheDocument();
  });

  it("submits the credentials and calls onLogin", async () => {
    const onLogin = vi.fn();
    const loginMock = vi.spyOn(api, "login").mockResolvedValueOnce({
      token: "test-token",
      user: { groups: ["radiologist"] }
    });

    render(<MemoryRouter><Login onLogin={onLogin} /></MemoryRouter>);
    await userEvent.click(screen.getByText("Login using demo credentials"));
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(loginMock).toHaveBeenCalledWith("radiologist", "<NewPassword1!>");
    expect(onLogin).toHaveBeenCalledWith({
      token: "test-token",
      user: { groups: ["radiologist"] }
    });

    loginMock.mockRestore();
  });
});
