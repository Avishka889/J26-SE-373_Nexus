/**
 * The error boundary every rendered tree sits in.
 *
 * Two of them: the root one around the whole app, whose fallback is a full
 * page, and one inside the shell around each page, keyed by the address, whose
 * fallback is a panel in the page's place. A page that fails to render takes
 * only itself down, and moving to another page leaves it behind.
 */

import { Component, type ErrorInfo, type ReactNode } from "react";
import { logger } from "@/lib/logger";
import { telemetry } from "@/lib/telemetry";
import { AppError } from "./PageError";

interface Props {
  children: ReactNode;
  /** What shows instead of what failed; a function gets the error and a way to try again. */
  fallback?: ReactNode | ((error: Error, reset: () => void) => ReactNode);
  /** A change clears the error: the address, for a page. */
  resetKey?: unknown;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: unknown): State {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    logger.error("Unhandled render error", { name: error.name, message: error.message });
    telemetry.captureException(error, { componentStack: info.componentStack });
  }

  componentDidUpdate(previous: Props) {
    if (this.state.error && previous.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  reset = () => this.setState({ error: null });

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    const { fallback } = this.props;
    if (typeof fallback === "function") return fallback(error, this.reset);
    return fallback ?? <AppError error={error} />;
  }
}
