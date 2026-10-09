/**
 * A profile photo, made small before it is saved.
 *
 * The photo is kept in the settings as a data URL, and every settings read
 * returns it: a 2 MB file became a 2.7 MB string on each one. It is only ever
 * shown in a circle at most 64 pixels across, so it is cropped to the square
 * that circle shows and scaled to 256 pixels, which as a JPEG is tens of
 * kilobytes. The server refuses anything much larger.
 */

/** The side of the saved square, in pixels: four times the largest circle it fills. */
export const PHOTO_SIZE = 256;

/** The largest file handed to the browser to decode. A phone's photo fits. */
export const PHOTO_MAX_BYTES = 20 * 1024 * 1024;

/**
 * The centred square of a picture `width` by `height`, and the side it is
 * drawn at: `max`, or the square's own side when that is smaller, since
 * enlarging a small picture only makes it bigger to send.
 */
export function squareCrop(width: number, height: number, max = PHOTO_SIZE) {
  const side = Math.min(width, height);
  return {
    sx: Math.floor((width - side) / 2),
    sy: Math.floor((height - side) / 2),
    side,
    size: Math.max(1, Math.min(max, side)),
  };
}

/** The picture as a small square JPEG data URL. Throws when the browser cannot read it. */
export async function shrinkPhoto(file: Blob, max = PHOTO_SIZE): Promise<string> {
  // Applies the photo's EXIF orientation by default, so a phone's photo stays upright.
  const bitmap = await createImageBitmap(file);
  try {
    const { sx, sy, side, size } = squareCrop(bitmap.width, bitmap.height, max);
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("This browser cannot draw the photo.");
    // A JPEG has no transparency: a transparent PNG would come out black.
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, size, size);
    context.imageSmoothingQuality = "high";
    context.drawImage(bitmap, sx, sy, side, side, 0, 0, size, size);
    return canvas.toDataURL("image/jpeg", 0.85);
  } finally {
    bitmap.close();
  }
}
