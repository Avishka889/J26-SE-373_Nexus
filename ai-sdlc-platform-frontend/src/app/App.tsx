import { AppProviders } from "@/app/providers";
import { AppRoutes } from "@/app/routes";

/** Root shell: every route inherits Inter from assets/fonts via `font-sans`. */
export default function App() {
  return (
    <div className="font-sans min-h-full h-full">
      <AppProviders>
        <AppRoutes />
      </AppProviders>
    </div>
  );
}
