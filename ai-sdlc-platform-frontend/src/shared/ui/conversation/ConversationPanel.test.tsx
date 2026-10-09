import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ConversationPanel } from "./ConversationPanel";
import type { ConversationMessage } from "./types";

afterEach(cleanup);

/**
 * The conversation as a document, in the manner of the agent tools people know:
 * what a person wrote in a bubble, what an agent did as a step with its prose, a
 * stage it produced as a card to open, and the platform's records as quiet
 * lines that fold when there are several in a row.
 */
function show(messages: ConversationMessage[], onSubmit = vi.fn()) {
  render(
    <ConversationPanel
      title="Conversation"
      subtitle="Everything that happened, oldest first"
      messages={messages}
      composer={{ placeholder: "Say what should change", helper: "Sending starts a run", pending: false, onSubmit }}
      onClose={vi.fn()}
    />,
  );
  return { onSubmit };
}

describe("the conversation", () => {
  it("shows what a person wrote as a bubble, with who and when under it", () => {
    show([{ id: "1", role: "user", author: "You", content: "Build a book tracker.", at: "09:12" }]);

    expect(screen.getByText("Build a book tracker.")).toBeTruthy();
    expect(screen.getByText("You")).toBeTruthy();
    expect(screen.getByText("09:12")).toBeTruthy();
  });

  it("shows an agent's stage as a card that opens it", () => {
    const onOpen = vi.fn();
    show([
      {
        id: "1",
        role: "agent",
        author: "Design agent",
        content: "Six requirements, read from the brief.",
        at: "09:13",
        chip: "Requirements",
        onOpen,
        openLabel: "Open Requirements",
      },
    ]);

    screen.getByRole("button", { name: "Open Requirements" }).click();

    expect(onOpen).toHaveBeenCalledOnce();
    expect(screen.getByText("Six requirements, read from the brief.")).toBeTruthy();
  });

  it("takes an answer where the question is asked", () => {
    const onSubmit = vi.fn();
    show([
      {
        id: "q",
        role: "agent",
        author: "Design agent",
        content: "Who may delete a book?",
        at: "09:14",
        answer: { placeholder: "Answer in a sentence", onSubmit },
      },
    ]);

    fireEvent.change(screen.getByPlaceholderText("Answer in a sentence"), {
      target: { value: "Only the reader who added it." },
    });
    screen.getByRole("button", { name: "Answer" }).click();

    expect(onSubmit).toHaveBeenCalledWith("Only the reader who added it.");
  });

  it("folds three records in a row into one line that opens to all of them", () => {
    show(
      ["Run started", "Stage complete", "Reached the review"].map((content, index) => ({
        id: String(index),
        role: "system" as const,
        author: "platform",
        content,
        at: `09:1${index}`,
      })),
    );

    const fold = screen.getByRole("button", { name: /3 recorded events/ });
    expect(screen.queryByText("Run started")).toBeNull();
    fireEvent.click(fold);

    expect(fold.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("Run started")).toBeTruthy();
  });

  it("offers the way back to the newest message once the reader scrolls away", () => {
    const messages = Array.from({ length: 4 }, (_, index) => ({
      id: String(index),
      role: "user" as const,
      author: "You",
      content: `note ${index}`,
      at: "09:00",
    }));
    const { container } = render(
      <ConversationPanel
        title="Conversation"
        subtitle=""
        messages={messages}
        composer={{ placeholder: "", helper: "", pending: false, onSubmit: vi.fn() }}
        onClose={vi.fn()}
      />,
    );
    const list = container.querySelector("ol.overscroll-contain") as HTMLOListElement;
    Object.defineProperty(list, "scrollHeight", { value: 2000, configurable: true });
    Object.defineProperty(list, "clientHeight", { value: 400, configurable: true });
    list.scrollTop = 100;

    fireEvent.scroll(list);
    fireEvent.click(screen.getByRole("button", { name: /scroll to latest/i }));

    expect(screen.queryByRole("button", { name: /scroll to latest/i })).toBeNull();
  });

  it("sends what is typed in the box", () => {
    const { onSubmit } = show([]);

    fireEvent.change(screen.getByPlaceholderText("Say what should change"), {
      target: { value: "Add a genre field." },
    });
    screen.getByRole("button", { name: "Send" }).click();

    expect(onSubmit).toHaveBeenCalledWith("Add a genre field.");
  });
});

/**
 * What a person typed survives a refusal.
 *
 * The box used to empty the moment Send was pressed, before the server had
 * answered. A refused change request (no review waiting, a run in flight, the
 * network gone) took the text with it, and it had to be written again from
 * memory. The box now empties only when the send is accepted.
 */
describe("sending from the composer", () => {
  function compose(onSubmit: (text: string) => void | Promise<unknown>, unavailable?: string) {
    render(
      <ConversationPanel
        title="Conversation"
        subtitle="Everything that happened, oldest first"
        messages={[]}
        composer={{
          placeholder: "Say what should change",
          helper: "Sending requests changes at the review",
          pending: false,
          onSubmit,
          unavailable,
        }}
        onClose={vi.fn()}
      />,
    );
    return screen.getByPlaceholderText("Say what should change") as HTMLTextAreaElement;
  }

  it("keeps what was typed when the send is refused", async () => {
    const onSubmit = vi.fn(() => Promise.reject(new Error("There is no code decision waiting")));
    const box = compose(onSubmit);

    fireEvent.change(box, { target: { value: "Split the order endpoints." } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith("Split the order endpoints."));
    await Promise.resolve();
    expect(box.value).toBe("Split the order endpoints.");
  });

  it("empties the box once the send is accepted", async () => {
    const box = compose(vi.fn(() => Promise.resolve()));

    fireEvent.change(box, { target: { value: "Split the order endpoints." } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(box.value).toBe(""));
  });

  it("keeps what was typed after Send while the send was on its way", async () => {
    let accept: () => void = () => undefined;
    const box = compose(vi.fn(() => new Promise<void>((resolve) => (accept = resolve))));

    fireEvent.change(box, { target: { value: "Split the order endpoints." } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    fireEvent.change(box, { target: { value: "And keep cancelling separate." } });
    accept();

    await waitFor(() => expect(box.value).toBe("And keep cancelling separate."));
  });

  it("says why it cannot send, and does not", () => {
    const onSubmit = vi.fn();
    const box = compose(onSubmit, "No review is waiting. Change requests open at the code review.");

    fireEvent.change(box, { target: { value: "Split the order endpoints." } });
    fireEvent.keyDown(box, { key: "Enter" });

    expect(screen.getByText("No review is waiting. Change requests open at the code review.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Send" }) as HTMLButtonElement).disabled).toBe(true);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("keeps an answer when it is refused", async () => {
    const onSubmit = vi.fn(() => Promise.reject(new Error("That question was already answered")));
    render(
      <ConversationPanel
        title="Conversation"
        subtitle="Everything that happened, oldest first"
        messages={[
          {
            id: "q",
            role: "agent",
            author: "Design agent",
            content: "Who may delete a book?",
            at: "09:14",
            answer: { placeholder: "Answer in a sentence", onSubmit },
          },
        ]}
        composer={{ placeholder: "Say what should change", helper: "", pending: false, onSubmit: vi.fn() }}
        onClose={vi.fn()}
      />,
    );
    const reply = screen.getByPlaceholderText("Answer in a sentence") as HTMLInputElement;

    fireEvent.change(reply, { target: { value: "Only the reader who added it." } });
    fireEvent.click(screen.getByRole("button", { name: "Answer" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    await Promise.resolve();
    expect(reply.value).toBe("Only the reader who added it.");
  });
});

/**
 * What a send runs on, said under the box, as a chat box in other tools names
 * its model: a reader should not have to open Settings to learn whether the
 * change they are about to request will think.
 */
describe("what a send runs on", () => {
  function composeWith(runsOn?: { text: string; to?: string }) {
    render(
      <MemoryRouter>
        <ConversationPanel
          title="Conversation"
          subtitle="Everything that happened, oldest first"
          messages={[]}
          composer={{
            placeholder: "Say what should change",
            helper: "Sending requests changes at the review",
            pending: false,
            onSubmit: vi.fn(),
            runsOn,
          }}
          onClose={vi.fn()}
        />
      </MemoryRouter>,
    );
  }

  it("says it under the box, with a way to where it is chosen", () => {
    composeWith({
      text: "This run: deepseek:deepseek-flash, thinking off. Next run: thinking on, high effort.",
      to: "/settings?tab=ai",
    });

    expect(
      screen.getByText(
        "This run: deepseek:deepseek-flash, thinking off. Next run: thinking on, high effort.",
      ),
    ).toBeTruthy();
    const settings = screen.getByRole("link", {
      name: "Choose how hard each phase thinks, in Settings",
    });
    expect(settings.getAttribute("href")).toBe("/settings?tab=ai");
  });

  it("offers no way to change what cannot be chosen, and says nothing where there is nothing to say", () => {
    composeWith({ text: "Next run: deepseek:deepseek-flash, thinking left to the provider." });
    expect(screen.getByText("Next run: deepseek:deepseek-flash, thinking left to the provider.")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();

    cleanup();
    composeWith(undefined);
    expect(screen.queryByText(/run:/)).toBeNull();
  });
});
