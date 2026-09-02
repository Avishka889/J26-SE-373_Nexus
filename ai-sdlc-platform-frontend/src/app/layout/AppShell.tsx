import { type ReactNode, useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { ErrorBoundary } from "@/app/errors/ErrorBoundary";
import { PageError } from "@/app/errors/PageError";
import { ChevronsLeft, ChevronsRight } from "lucide-react";
import { useUiStore } from "@/store/ui";
import { Sidebar } from "@/app/layout/Sidebar";
import { TopBar } from "@/app/layout/TopBar";
import { cn } from "@/shared/utils/cn";

export function AppShell({ children }: { children: ReactNode }) {
  const theme = useUiStore((s) => s.theme);
  const isDark = theme === "dark";
  const location = useLocation();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const menuTriggerRef = useRef<HTMLButtonElement | null>(null);
  // After a navigation, focus starts at the page, as a page load starts it;
  // it stayed on the link just used, wherever that was. Not on the first
  // render: arriving at the app is not a move within it.
  const mainRef = useRef<HTMLElement | null>(null);
  const arrived = useRef(false);
  useEffect(() => {
    if (!arrived.current) {
      arrived.current = true;
      return;
    }
    mainRef.current?.focus({ preventScroll: true });
  }, [location.pathname]);

  // Track whether the sidebar is currently the drawer, so the dialog semantics
  // only apply when it actually behaves like one.
  const [isMobileViewport, setIsMobileViewport] = useState(
    () =>
      typeof window !== "undefined" &&
      !window.matchMedia("(min-width: 768px)").matches,
  );

  useEffect(() => {
    const query = window.matchMedia("(min-width: 768px)");
    const sync = () => {
      setIsMobileViewport(!query.matches);
      if (query.matches) setMobileOpen(false);
    };
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);

  // Close the mobile drawer on route change.
  //
  // Adjusted during render rather than in an effect: the drawer must be shut in
  // the same paint that shows the new route, and an effect closes it one render
  // later, which is a visible flash of the old drawer over the new page. React
  // supports exactly this shape for "reset state when a value changes".
  const [pathAtRender, setPathAtRender] = useState(location.pathname);
  if (pathAtRender !== location.pathname) {
    setPathAtRender(location.pathname);
    setMobileOpen(false);
  }

  // Close drawer when resizing to desktop
  useEffect(() => {
    const onResize = () => {
      if (window.matchMedia("(min-width: 768px)").matches) setMobileOpen(false);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // Escape closes the drawer and focus returns to the trigger, as with any
  // modal surface.
  useEffect(() => {
    if (!mobileOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setMobileOpen(false);
      menuTriggerRef.current?.focus();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [mobileOpen]);

  // Lock body scroll when mobile menu is open
  useEffect(() => {
    if (!mobileOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [mobileOpen]);

  return (
    <div
      className={cn(
        "relative flex h-[100dvh] overflow-hidden transition-colors",
        isDark ? "bg-[#071018]" : "bg-white",
      )}
    >
      {/* The first thing Tab reaches: past the sidebar and the top bar, which
          a keyboard otherwise walks through on every page. */}
      <a
        href="#main"
        onClick={(event) => {
          event.preventDefault();
          mainRef.current?.focus();
        }}
        className="sr-only z-[100] rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white focus:not-sr-only focus:absolute focus:left-3 focus:top-3"
      >
        Skip to the page
      </a>
      {/* Mobile overlay */}
      {mobileOpen && (
        <button
          type="button"
          aria-label="Close menu"
          className="fixed inset-0 z-40 bg-slate-950/40 backdrop-blur-[2px] md:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      <Sidebar
        collapsed={sidebarCollapsed}
        mobileOpen={mobileOpen}
        isMobileViewport={isMobileViewport}
        onNavigate={() => setMobileOpen(false)}
      />

      <button
        type="button"
        onClick={() => setSidebarCollapsed((prev) => !prev)}
        aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        className={cn(
          "absolute top-4 z-40 hidden h-6 w-6 -translate-x-1/2 items-center justify-center rounded-full border border-blue-600 bg-blue-600 text-white shadow-md shadow-blue-500/25 transition-all duration-300 ease-in-out hover:bg-blue-500 md:flex",
          sidebarCollapsed ? "left-[68px]" : "left-[252px]",
        )}
      >
        {sidebarCollapsed ? (
          <ChevronsRight className="h-3.5 w-3.5" />
        ) : (
          <ChevronsLeft className="h-3.5 w-3.5" />
        )}
      </button>

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <TopBar
          onOpenMobileNav={() => setMobileOpen(true)}
          mobileOpen={mobileOpen}
          menuTriggerRef={menuTriggerRef}
        />
        <main
          id="main"
          ref={mainRef}
          tabIndex={-1}
          className="relative flex-1 overflow-auto overscroll-contain outline-none"
        >
          <div
            className={cn(
              "pointer-events-none absolute inset-x-0 top-0 z-0 h-72 bg-gradient-to-b",
              isDark
                ? "from-blue-500/[0.07] to-transparent"
                : "from-blue-100/60 to-transparent",
            )}
          />
          {/* Positioned, but deliberately without a z-index.
           *
           * `z-[1]` here put the content above the wash and, in doing so, made
           * this a stacking context: every overlay a page renders was sealed
           * inside it at z-index 1, so the top bar's z-30 painted over them. The
           * prototype modal was dimmed by its own backdrop while the search box
           * and the notification bell stayed live above it, and the conversation
           * sheet on a phone had the same problem.
           *
           * `z-index: auto` creates no stacking context, and the content still
           * paints above the wash because it comes after it in the document and
           * both are in the same layer. So a modal inside a page can reach the
           * top of the window, which is what a modal is. */}
          {/* h-full, not min-h-full. A percentage height resolves only against a
              definite one, and min-height is not definite: a page asking for
              h-full got auto instead and grew with its content. Pages taller
              than this still overflow it and still scroll, because main is the
              scrollport; pages that want to own their own height can now have
              it. */}
          <div className="relative h-full min-w-0">
            {/* Each page in its own boundary, keyed by the address: a page that
                fails to render is replaced by a panel saying so, the shell
                around it keeps working, and moving to another page leaves the
                failure behind. */}
            <ErrorBoundary
              resetKey={location.pathname}
              fallback={(error, reset) => <PageError error={error} onRetry={reset} />}
            >
              {children}
            </ErrorBoundary>
          </div>
        </main>
      </div>
    </div>
  );
}

export { AppShell as Layout };
