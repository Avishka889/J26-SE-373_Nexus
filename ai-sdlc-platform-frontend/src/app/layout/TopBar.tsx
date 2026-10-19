import { env } from "@/lib/env";
import { alertsFor, alertsFromAttention } from "./alerts";
import { useEffect, useRef, useState, type RefObject } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Search,
  Bell,
  Command,
  AlertTriangle,
  Info,
  X,
  Menu,
} from "lucide-react";
import { useUiStore } from "@/store/ui";
import { useProjectsList } from "@/entities/project";
import { useSettings } from "@/entities/settings";
import { useAttention } from "@/entities/attention";
import { cn } from "@/shared/utils/cn";

export function TopBar({
  onOpenMobileNav,
  mobileOpen,
  menuTriggerRef,
}: {
  onOpenMobileNav: () => void;
  mobileOpen: boolean;
  menuTriggerRef: RefObject<HTMLButtonElement | null>;
}) {
  const setCommandPaletteOpen = useUiStore((s) => s.setCommandPaletteOpen);
  const addToast = useUiStore((s) => s.addToast);
  const theme = useUiStore((s) => s.theme);
  const settings = useSettings();
  const projects = useProjectsList();
  const [showNotifications, setShowNotifications] = useState(false);
  const notificationsRef = useRef<HTMLDivElement>(null);
  const bellRef = useRef<HTMLButtonElement>(null);
  // An open panel closes on a press anywhere else and on Escape, as a menu
  // does; only its X closed it. Escape hands the focus back to the bell.
  useEffect(() => {
    if (!showNotifications) return;
    const onPress = (event: MouseEvent) => {
      if (!notificationsRef.current?.contains(event.target as Node))
        setShowNotifications(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setShowNotifications(false);
      bellRef.current?.focus();
    };
    document.addEventListener("mousedown", onPress);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPress);
      document.removeEventListener("keydown", onKey);
    };
  }, [showNotifications]);
  const isDark = theme === "dark";
  const location = useLocation();
  const navigate = useNavigate();
  // What waits on the signed-in person, from the server; fixtures keep their
  // demo lines, which say nothing about any real project.
  const attention = useAttention(!env.allFixtures);

  const title = (() => {
    if (location.pathname === "/workspace") return "Home";
    if (location.pathname.startsWith("/projects/new")) return "New project";
    if (
      location.pathname.startsWith("/projects/") &&
      location.pathname.includes("/requirements")
    )
      return "Requirements & Design";
    if (
      location.pathname.startsWith("/projects/") &&
      location.pathname.includes("/code")
    )
      return "Code Generation";
    if (
      location.pathname.startsWith("/projects/") &&
      location.pathname.includes("/testing")
    )
      return "Testing & Security";
    if (
      location.pathname.startsWith("/projects/") &&
      location.pathname.includes("/deployment")
    )
      return "Deployment";
    if (
      location.pathname.startsWith("/projects/") &&
      location.pathname.includes("/traceability")
    )
      return "Activity Log";
    if (location.pathname.startsWith("/projects")) return "Projects";
    if (location.pathname.startsWith("/settings")) return "Settings";
    return "Nexus";
  })();

  const alerts = env.allFixtures
    ? alertsFor(true, projects[0]?.name, settings.ai.model)
    : alertsFromAttention(attention);

  return (
    <header
      className={cn(
        "relative z-30 flex h-14 shrink-0 items-center gap-2 border-b px-3 backdrop-blur-xl sm:gap-3 sm:px-6",
        isDark
          ? "border-white/[0.06] bg-[#0a1628]/85"
          : "border-slate-200/80 bg-white/95",
      )}
    >
      <button
        type="button"
        ref={menuTriggerRef}
        onClick={onOpenMobileNav}
        aria-label="Open menu"
        aria-haspopup="dialog"
        aria-expanded={mobileOpen}
        aria-controls="app-sidebar"
        className={cn(
          "flex h-9 w-9 shrink-0 items-center justify-center rounded-full border md:hidden",
          isDark
            ? "border-white/10 bg-white/[0.04] text-slate-300"
            : "border-slate-200 bg-white text-slate-600",
        )}
      >
        <Menu className="h-4 w-4" />
      </button>

      <h1
        className={cn(
          "min-w-0 truncate text-[14px] font-semibold tracking-tight sm:text-[15px]",
          isDark ? "text-white" : "text-slate-900",
        )}
      >
        {title}
      </h1>

      <button
        onClick={() => setCommandPaletteOpen(true)}
        className={cn(
          "ml-auto flex h-9 items-center gap-2 rounded-full border px-2.5 text-[13px] transition-all sm:w-64 sm:px-3.5",
          isDark
            ? "border-white/10 bg-white/[0.04] text-slate-400 hover:border-white/15"
            : "border-slate-200 bg-white text-slate-500 hover:border-blue-200 hover:bg-blue-50/30",
        )}
      >
        <Search className="h-3.5 w-3.5 shrink-0" />
        <span className="hidden flex-1 text-left sm:inline">Search...</span>
        <kbd
          className={cn(
            "hidden items-center gap-0.5 rounded-md border px-1.5 py-0.5 text-[10px] sm:flex",
            isDark
              ? "border-white/10 bg-white/5 text-slate-400"
              : "border-slate-200 bg-white text-slate-500",
          )}
        >
          <Command className="h-2.5 w-2.5" />K
        </kbd>
      </button>

      <div className="relative" ref={notificationsRef}>
        <button
          type="button"
          ref={bellRef}
          aria-label={
            alerts.length > 0
              ? `Notifications, ${alerts.length} waiting`
              : "Notifications"
          }
          aria-expanded={showNotifications}
          aria-controls="notifications-panel"
          onClick={() => setShowNotifications(!showNotifications)}
          className={cn(
            "relative flex h-9 w-9 items-center justify-center rounded-full border transition-colors",
            isDark
              ? "border-white/10 bg-white/[0.04] text-slate-400"
              : "border-slate-200 bg-slate-50 text-slate-500",
          )}
        >
          <Bell className="h-4 w-4" aria-hidden="true" />
          {alerts.length > 0 && (
            <span
              aria-hidden="true"
              className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-blue-600 px-1 text-[9px] font-bold text-white"
            >
              {alerts.length}
            </span>
          )}
        </button>
        {showNotifications && (
          <div
            id="notifications-panel"
            role="region"
            aria-label="Notifications"
            className={cn(
              "absolute right-0 top-11 z-50 w-[min(20rem,calc(100vw-1.5rem))] overflow-hidden rounded-2xl border shadow-2xl isolate",
              isDark
                ? "border-white/10 bg-[#0f1d32]"
                : "border-slate-200 bg-white",
            )}
          >
            <div
              className="flex items-center justify-between border-b px-4 py-3"
              style={{
                borderColor: isDark ? "rgba(255,255,255,0.06)" : "#f1f5f9",
              }}
            >
              <span
                className={cn(
                  "text-sm font-semibold",
                  isDark ? "text-white" : "text-slate-900",
                )}
              >
                Notifications
              </span>
              <button
                type="button"
                aria-label="Close notifications"
                onClick={() => setShowNotifications(false)}
              >
                <X
                  aria-hidden="true"
                  className={cn(
                    "h-4 w-4",
                    isDark ? "text-slate-400" : "text-slate-500",
                  )}
                />
              </button>
            </div>
            {alerts.length === 0 && (
              <p
                className={cn(
                  "px-4 py-4 text-[13px]",
                  isDark ? "text-slate-400" : "text-slate-500",
                )}
              >
                Nothing needs you right now.
              </p>
            )}
            {/* The panel clips, so the list is what scrolls: a long one was
                cut off at the panel's edge. */}
            {alerts.length > 0 && (
              <ul className="max-h-80 space-y-0.5 overflow-y-auto overscroll-contain p-2">
                {alerts.map((alert) => {
                  const Icon =
                    alert.severity === "warning" ? AlertTriangle : Info;
                  return (
                    <li key={alert.id}>
                      <button
                        type="button"
                        onClick={() => {
                          setShowNotifications(false);
                          // A line opens the page where it is decided; a demo
                          // line has nowhere to go, so it says itself instead.
                          if (alert.href) {
                            navigate(alert.href);
                            return;
                          }
                          addToast({
                            type: "info",
                            title: alert.title,
                            message: alert.message,
                          });
                        }}
                        className={cn(
                          "flex w-full gap-3 rounded-xl p-2.5 text-left",
                          isDark
                            ? "hover:bg-white/[0.04]"
                            : "hover:bg-slate-50",
                        )}
                      >
                        <Icon
                          aria-hidden="true"
                          className={cn(
                            "mt-0.5 h-4 w-4 shrink-0",
                            alert.severity === "warning"
                              ? "text-amber-500"
                              : "text-blue-500",
                          )}
                        />
                        <div>
                          <p
                            className={cn(
                              "text-[13px] font-medium",
                              isDark ? "text-slate-200" : "text-slate-800",
                            )}
                          >
                            {alert.title}
                          </p>
                          <p
                            className={cn(
                              "text-xs",
                              isDark ? "text-slate-400" : "text-slate-500",
                            )}
                          >
                            {alert.message}
                          </p>
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        )}
      </div>
    </header>
  );
}
