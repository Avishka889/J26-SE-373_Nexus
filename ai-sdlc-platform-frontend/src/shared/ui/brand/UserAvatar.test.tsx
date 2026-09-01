import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { shrinkPhoto } from "@/shared/utils/photo";
import { ProfilePhotoEditor, UserAvatar } from "./UserAvatar";

// jsdom draws nothing, so the shrinking itself is stood in for; what is tested
// is that the picker saves what the shrinking made, never the file's own bytes.
vi.mock("@/shared/utils/photo", async (actual) => ({
  ...(await actual<typeof import("@/shared/utils/photo")>()),
  shrinkPhoto: vi.fn(),
}));

/**
 * Somebody without a photo is shown by their initials. A missing photo used to
 * be the demo profile's stock portrait, which then stood for anybody.
 */
afterEach(cleanup);

describe("an avatar", () => {
  it.each([undefined, "", null])(
    "shows initials, not a stock photo, for %s",
    (avatarUrl) => {
      const { container } = render(
        <UserAvatar name="Sampath Vinoshan" avatarUrl={avatarUrl} />,
      );
      expect(container.querySelector("img")).toBeNull();
      expect(container.textContent).toContain("SV");
    },
  );

  it("shows the photo it is given", () => {
    const { container } = render(
      <UserAvatar
        name="Sampath Vinoshan"
        avatarUrl="https://example.invalid/me.png"
      />,
    );
    expect(container.querySelector("img")?.getAttribute("src")).toBe(
      "https://example.invalid/me.png",
    );
  });
});

describe("choosing a photo", () => {
  const pick = (file: File) => {
    const onAvatarChange = vi.fn();
    const onError = vi.fn();
    const { container } = render(
      <ProfilePhotoEditor
        isDark={false}
        name="Sampath Vinoshan"
        email="s@example.invalid"
        onAvatarChange={onAvatarChange}
        onAvatarRemove={vi.fn()}
        onError={onError}
      />,
    );
    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    fireEvent.change(input!, { target: { files: [file] } });
    return { onAvatarChange, onError };
  };
  const photo = (bytes = 3 * 1024 * 1024) =>
    new File([new Uint8Array(bytes)], "me.jpg", { type: "image/jpeg" });

  it("saves the small square made from it, not the file as it was", async () => {
    vi.mocked(shrinkPhoto).mockResolvedValue("data:image/jpeg;base64,c21hbGw=");

    const { onAvatarChange, onError } = pick(photo());

    await waitFor(() => expect(onAvatarChange).toHaveBeenCalledWith("data:image/jpeg;base64,c21hbGw="));
    expect(onError).not.toHaveBeenCalled();
  });

  it("says so when the image cannot be read, and saves nothing", async () => {
    vi.mocked(shrinkPhoto).mockRejectedValue(new Error("The source image could not be decoded."));

    const { onAvatarChange, onError } = pick(photo());

    await waitFor(() => expect(onError).toHaveBeenCalledWith("Photo not read", expect.any(String)));
    expect(onAvatarChange).not.toHaveBeenCalled();
  });

  it("refuses a file that is not an image without reading it", () => {
    vi.mocked(shrinkPhoto).mockClear();

    const { onAvatarChange, onError } = pick(new File(["%PDF"], "cv.pdf", { type: "application/pdf" }));

    expect(onError).toHaveBeenCalledWith("Invalid file", "Please choose an image");
    expect(shrinkPhoto).not.toHaveBeenCalled();
    expect(onAvatarChange).not.toHaveBeenCalled();
  });
});
