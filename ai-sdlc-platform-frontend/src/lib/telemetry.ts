/**
 * Optional analytics / error-reporting hooks.
 * Wire a real provider (e.g. Datadog RUM) without leaking PII.
 */

export const telemetry = {
  track(event: string, properties?: Record<string, unknown>): void {
    if (import.meta.env.DEV) {
      console.debug("[telemetry]", event, properties);
    }
  },

  captureException(error: unknown, context?: Record<string, unknown>): void {
    if (import.meta.env.DEV) {
      console.debug("[telemetry:error]", error, context);
    }
  },
};
