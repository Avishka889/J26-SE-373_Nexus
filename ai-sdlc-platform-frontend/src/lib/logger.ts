/**
 * Structured client logging. Never log PII, tokens, or request Authorization headers.
 */

type LogLevel = "debug" | "info" | "warn" | "error";

function emit(level: LogLevel, message: string, context?: Record<string, unknown>) {
  const payload = context ? { message, ...context } : { message };
  const method = level === "debug" ? "log" : level;
  console[method](`[nexus:${level}]`, payload);
}

export const logger = {
  debug: (message: string, context?: Record<string, unknown>) => emit("debug", message, context),
  info: (message: string, context?: Record<string, unknown>) => emit("info", message, context),
  warn: (message: string, context?: Record<string, unknown>) => emit("warn", message, context),
  error: (message: string, context?: Record<string, unknown>) => emit("error", message, context),
};
