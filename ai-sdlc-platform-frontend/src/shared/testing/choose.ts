import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

/**
 * Choose an option of the platform's dropdown, as a person does: open it, then
 * press the option. The list is not in the page until it is opened, so a
 * change event on the trigger, which drove the native control, does nothing.
 */
export async function choose(trigger: HTMLElement, option: string | RegExp): Promise<void> {
  await userEvent.click(trigger);
  await userEvent.click(await screen.findByRole("option", { name: option }));
}
