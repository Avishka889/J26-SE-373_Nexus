import { useRef, type ChangeEvent, type ReactNode } from "react";
import { Camera, Trash2 } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { PHOTO_MAX_BYTES, shrinkPhoto } from "@/shared/utils/photo";

function initialsOf(name: string) {
  return name
    .split(" ")
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export type UserAvatarProps = {
  name: string;
  avatarUrl?: string | null;
  size?: "sm" | "md" | "lg";
  /** Hover overlay with change/remove actions */
  editable?: boolean;
  className?: string;
  onAvatarChange?: (dataUrl: string) => void;
  onAvatarRemove?: () => void;
  onError?: (title: string, message?: string) => void;
};

const sizeClass = {
  sm: "h-8 w-8 text-[11px]",
  md: "h-12 w-12 text-sm",
  lg: "h-16 w-16 text-lg",
} as const;

/**
 * The photo to show, or null for initials. A missing photo is initials: it used
 * to be the demo profile's stock portrait, which then stood for whoever had not
 * chosen one. The demo passes that portrait as its own photo, so it keeps it.
 */
function resolveAvatar(avatarUrl: string | null | undefined) {
  return avatarUrl ? avatarUrl : null;
}

/**
 * The picked file, checked and made small, handed on as a data URL.
 *
 * Both pickers below use it. The photo is saved into the settings, which every
 * settings read returns, so it is cropped and shrunk before it leaves the
 * browser; the file's own bytes were sent as they were.
 */
async function takePhoto(
  event: ChangeEvent<HTMLInputElement>,
  onAvatarChange: ((dataUrl: string) => void) | undefined,
  onError: ((title: string, message?: string) => void) | undefined,
) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  if (!file.type.startsWith("image/")) {
    onError?.("Invalid file", "Please choose an image");
    return;
  }
  if (file.size > PHOTO_MAX_BYTES) {
    onError?.("Image too large", "Choose an image under 20 MB");
    return;
  }
  let photo: string;
  try {
    photo = await shrinkPhoto(file);
  } catch {
    onError?.("Photo not read", "This image could not be read. Choose a JPG, PNG or WebP image.");
    return;
  }
  onAvatarChange?.(photo);
}

/** Presentational avatar, with no store or feature imports. */
export function UserAvatar({
  name,
  avatarUrl,
  size = "sm",
  editable = false,
  className,
  onAvatarChange,
  onAvatarRemove,
  onError,
}: UserAvatarProps) {
  const fileRef = useRef<HTMLInputElement | null>(null);
  const src = resolveAvatar(avatarUrl);

  const onPick = () => fileRef.current?.click();

  const onFile = (event: ChangeEvent<HTMLInputElement>) =>
    void takePhoto(event, onAvatarChange, onError);

  return (
    <div className={cn("relative shrink-0", sizeClass[size], className)}>
      {src ? (
        <img
          src={src}
          alt={name}
          className="h-full w-full rounded-full object-cover shadow-sm ring-2 ring-white"
        />
      ) : (
        <span className="flex h-full w-full items-center justify-center rounded-full bg-gradient-to-br from-blue-600 to-blue-400 font-bold text-white shadow-sm">
          {initialsOf(name)}
        </span>
      )}

      {editable && (
        <>
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={onFile}
          />
          <div className="absolute inset-0 flex items-center justify-center gap-1 rounded-full bg-slate-950/55 opacity-0 backdrop-blur-[1px] transition-opacity hover:opacity-100 focus-within:opacity-100">
            <button
              type="button"
              title="Change photo"
              aria-label="Change photo"
              onClick={onPick}
              className="flex h-7 w-7 items-center justify-center rounded-full bg-white text-slate-800 shadow-sm transition hover:bg-blue-50 hover:text-blue-600"
            >
              <Camera className="h-3.5 w-3.5" />
            </button>
            {src && onAvatarRemove && (
              <button
                type="button"
                title="Remove photo"
                aria-label="Remove photo"
                onClick={onAvatarRemove}
                className="flex h-7 w-7 items-center justify-center rounded-full bg-white text-red-600 shadow-sm transition hover:bg-red-50"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export type ProfilePhotoEditorProps = {
  isDark: boolean;
  name: string;
  email: string;
  avatarUrl?: string | null;
  onAvatarChange: (dataUrl: string) => void;
  onAvatarRemove: () => void;
  onError?: (title: string, message?: string) => void;
  footer?: ReactNode;
};

/** Presentational profile photo card. Wire the actions from settings or app. */
export function ProfilePhotoEditor({
  isDark,
  name,
  email,
  avatarUrl,
  onAvatarChange,
  onAvatarRemove,
  onError,
}: ProfilePhotoEditorProps) {
  const fileRef = useRef<HTMLInputElement | null>(null);
  const src = resolveAvatar(avatarUrl);

  const onFile = (event: ChangeEvent<HTMLInputElement>) =>
    void takePhoto(event, onAvatarChange, onError);

  return (
    <div
      className={cn(
        "flex flex-col gap-4 rounded-xl border border-dashed p-4 sm:flex-row sm:items-center",
        isDark ? "border-white/10" : "border-slate-200",
      )}
    >
      <UserAvatar
        size="lg"
        editable
        name={name}
        avatarUrl={avatarUrl}
        onAvatarChange={onAvatarChange}
        onAvatarRemove={onAvatarRemove}
        onError={onError}
      />
      <div className="min-w-0 flex-1">
        <p
          className={cn(
            "font-medium",
            isDark ? "text-white" : "text-slate-900",
          )}
        >
          {name}
        </p>
        <p
          className={cn(
            "text-sm",
            isDark ? "text-slate-400" : "text-slate-500",
          )}
        >
          {email}
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={onFile}
          />
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold transition",
              isDark
                ? "border-white/10 bg-white/[0.04] text-slate-200 hover:bg-white/[0.08]"
                : "border-slate-200 bg-white text-slate-700 hover:border-blue-200 hover:text-blue-600",
            )}
          >
            <Camera className="h-3.5 w-3.5" />
            Change photo
          </button>
          {src && (
            <button
              type="button"
              onClick={onAvatarRemove}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold transition",
                isDark
                  ? "border-red-500/20 bg-red-500/10 text-red-300 hover:bg-red-500/15"
                  : "border-red-200 bg-red-50 text-red-700 hover:bg-red-100",
              )}
            >
              <Trash2 className="h-3.5 w-3.5" />
              Remove
            </button>
          )}
        </div>
        <p
          className={cn(
            "mt-2 text-[11px]",
            isDark ? "text-slate-400" : "text-slate-500",
          )}
        >
          Any JPG, PNG or WebP image. It is cropped to a square and made small before it is saved.
        </p>
      </div>
    </div>
  );
}
