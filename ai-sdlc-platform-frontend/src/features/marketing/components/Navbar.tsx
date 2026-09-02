import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Menu, Upload, X } from "lucide-react";
import { NexusWordmark } from "@/shared/ui/brand/NexusWordmark";

const navLinks = [
  { label: "Home", href: "#home" },
  { label: "Features", href: "#features" },
  { label: "Solutions", href: "#solutions" },
  { label: "Availability", href: "#pricing" },
  { label: "Questions", href: "#docs" },
  { label: "Privacy", href: "#privacy" },
];

export function Navbar() {
  const navigate = useNavigate();
  const [mobileNav, setMobileNav] = useState(false);

  return (
    <header className="fixed inset-x-0 top-0 z-50 border-b border-white/40 bg-white/70 backdrop-blur-xl">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:h-16 sm:px-6 lg:px-8">
        <Link to="/" className="flex min-w-0 items-center">
          <NexusWordmark className="h-7 max-w-[140px] sm:h-9 sm:max-w-[180px]" />
        </Link>

        <nav className="hidden items-center gap-8 lg:flex">
          {navLinks.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className="text-sm font-medium text-slate-600 transition-colors hover:text-blue-600"
            >
              {link.label}
            </a>
          ))}
        </nav>

        <div className="hidden items-center gap-3 lg:flex">
          <button
            onClick={() => navigate("/login")}
            className="rounded-xl px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:text-blue-600"
          >
            Log In
          </button>
          <button
            onClick={() => navigate("/projects/new")}
            className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-medium text-white shadow-lg shadow-blue-600/25 transition-all hover:bg-blue-500"
          >
            <Upload className="h-4 w-4" />
            Upload SRS
          </button>
        </div>

        <button
          className="flex h-10 w-10 items-center justify-center rounded-xl text-slate-700 hover:bg-slate-100 lg:hidden"
          onClick={() => setMobileNav(!mobileNav)}
          aria-label="Menu"
        >
          {mobileNav ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </div>

      {mobileNav && (
        <div className="border-t border-slate-200/80 bg-white/95 px-4 py-4 safe-pb lg:hidden">
          <nav className="flex flex-col gap-1">
            {navLinks.map((link) => (
              <a
                key={link.href}
                href={link.href}
                onClick={() => setMobileNav(false)}
                className="rounded-xl px-3 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                {link.label}
              </a>
            ))}
            <hr className="my-2 border-slate-200" />
            <button
              onClick={() => navigate("/login")}
              className="rounded-xl px-3 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Log In
            </button>
            <button
              onClick={() => navigate("/projects/new")}
              className="mt-1 inline-flex items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-3 text-sm font-medium text-white"
            >
              <Upload className="h-4 w-4" />
              Upload SRS
            </button>
          </nav>
        </div>
      )}
    </header>
  );
}
