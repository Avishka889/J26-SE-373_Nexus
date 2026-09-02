export type { Attachment, AttachmentSlot, DocumentFormat } from "@/types/document";
export { CHAR_LIMIT, formatOf, normalise, truncate, countWords } from "./extract";
export { composeRequirementText } from "./compose";
export { extractDocument } from "./api";
export { useAttachments } from "./hooks";
