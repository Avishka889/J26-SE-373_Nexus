import {
  FileCode2,
  FileJson,
  FileType,
  Braces,
  TestTube2,
  Palette,
  Coffee,
  Database,
  Box,
  Layers,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

const extMap: Record<string, { icon: LucideIcon; color: string }> = {
  tsx: { icon: FileCode2, color: "#61dafb" },
  ts: { icon: FileType, color: "#3178c6" },
  css: { icon: Palette, color: "#a855f7" },
  java: { icon: Coffee, color: "#f89820" },
  json: { icon: FileJson, color: "#fbbf24" },
};

const typeMap: Record<string, { icon: LucideIcon; color: string }> = {
  component: { icon: Box, color: "#61dafb" },
  service: { icon: Layers, color: "#3b82f6" },
  hook: { icon: Braces, color: "#8b5cf6" },
  style: { icon: Palette, color: "#a855f7" },
  test: { icon: TestTube2, color: "#22c55e" },
  controller: { icon: FileCode2, color: "#f89820" },
  repository: { icon: Database, color: "#06b6d4" },
  entity: { icon: Box, color: "#f97316" },
  dto: { icon: FileType, color: "#eab308" },
};

export function getFileIcon(path: string, type?: string) {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  if (extMap[ext]) return extMap[ext];
  if (type && typeMap[type]) return typeMap[type];
  return { icon: FileCode2, color: "#94a3b8" };
}
