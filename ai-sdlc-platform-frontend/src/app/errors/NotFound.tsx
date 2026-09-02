import { Compass } from "lucide-react";
import { useDocumentTitle } from "@/shared/hooks";
import { Link } from "react-router-dom";
import { Note, Panel } from "@/shared/ui/phase";

/**
 * An address the app does not have.
 *
 * It used to redirect to Home without a word, so a mistyped or out of date
 * link looked like a link to Home.
 */
export function NotFound() {
  useDocumentTitle("Page not found");
  return (
    <div className="tp w-full p-4 sm:p-6 md:p-8">
      <Panel icon={<Compass className="h-4 w-4" />} label="This page does not exist">
        <Note>The address may be mistyped, or the page it pointed at may have moved.</Note>
        <div className="mt-3 flex flex-wrap gap-2">
          <Link
            to="/workspace"
            className="inline-flex items-center rounded-lg bg-blue-600 px-3 py-1.5 text-[13px] font-medium text-white transition-colors hover:bg-blue-500"
          >
            Go to Home
          </Link>
          <Link
            to="/projects"
            className="inline-flex items-center rounded-lg border border-[color:var(--tp-line-strong)] px-3 py-1.5 text-[13px] font-medium text-[color:var(--tp-ink)] transition-colors hover:bg-[color:var(--tp-line)]"
          >
            See your projects
          </Link>
        </div>
      </Panel>
    </div>
  );
}
