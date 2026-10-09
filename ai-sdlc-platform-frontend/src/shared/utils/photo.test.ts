import { describe, expect, it } from "vitest";
import { PHOTO_SIZE, squareCrop } from "./photo";

/**
 * A profile photo is shown in a circle, so what is kept is the centred square
 * the circle shows, at no more than 256 pixels: the whole file was kept, and
 * every settings read carried it.
 */
describe("the square kept of a photo", () => {
  it("takes the middle of a landscape picture, scaled down", () => {
    expect(squareCrop(4000, 3000)).toEqual({ sx: 500, sy: 0, side: 3000, size: PHOTO_SIZE });
  });

  it("takes the middle of a portrait picture, scaled down", () => {
    expect(squareCrop(3000, 4000)).toEqual({ sx: 0, sy: 500, side: 3000, size: PHOTO_SIZE });
  });

  it("does not enlarge a picture smaller than the saved square", () => {
    expect(squareCrop(120, 80)).toEqual({ sx: 20, sy: 0, side: 80, size: 80 });
  });

  it("keeps a square of exactly the saved size as it is", () => {
    expect(squareCrop(PHOTO_SIZE, PHOTO_SIZE)).toEqual({
      sx: 0,
      sy: 0,
      side: PHOTO_SIZE,
      size: PHOTO_SIZE,
    });
  });
});
