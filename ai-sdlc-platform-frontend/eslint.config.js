import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";

/**
 * Layer boundaries:
 *   app → features → shared / lib / types / store / entities
 *   features never import other features (relative imports within a feature)
 *   shared / lib / entities never import features or app
 *   Prefer shared area barrels; retired deep paths are hard errors.
 */
const sharedRetiredDeepPaths = [
  {
    name: "@/shared/ui/PhaseSectionHeader",
    message: "Import PhaseSectionHeader from @/shared/ui.",
  },
  {
    name: "@/shared/viz/MermaidDiagram",
    message: "Import MermaidDiagram from @/shared/viz.",
  },
  {
    name: "@/shared/viz/MermaidDiagramImpl",
    message: "Do not import MermaidDiagramImpl; use @/shared/viz.",
  },
  {
    name: "@/shared/hooks/useEditorTabs",
    message: "Import useEditorTabs from @/shared/hooks.",
  },
];

export default tseslint.config(
  // `public/` holds static assets, including the generated MSW service
  // worker, which is vendor code and not ours to lint.
  { ignores: ["dist", "e2e", "coverage", "scripts", "public"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      // An underscore prefix is how this codebase says "required by the signature,
      // deliberately unused". Without this the convention reads as a mistake and
      // the only way to satisfy the linter is to delete the name, which loses the
      // documentation of what the argument is.
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
        },
      ],
    },
  },
  {
    files: ["src/features/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          paths: sharedRetiredDeepPaths,
          patterns: [
            {
              group: ["@/features/*", "@/features/*/*", "@/features/*/**"],
              message:
                "Features must not import via @/features/*. Use relative imports within the feature, or compose in app/.",
            },
          ],
        },
      ],
    },
  },
  {
    files: ["src/app/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          paths: sharedRetiredDeepPaths,
          patterns: [
            {
              group: ["@/features/*/*", "@/features/*/**"],
              message:
                "Import features only through their public barrel (@/features/<name>), not deep paths.",
            },
          ],
        },
      ],
    },
  },
  {
    // MSW bootstrap may import feature msw entry points (not page barrels).
    files: ["src/mocks/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@/features/*/fixtures/*", "@/features/*/fixtures/**", "@/features/*/components/**"],
              message: "Mocks should import via @/features/<name>/msw (or the feature public barrel).",
            },
          ],
        },
      ],
    },
  },
  {
    // Components render what the api gives them. Reaching into fixtures is how a
    // display contract quietly stops being one.
    //
    // Two phases now: Requirements and Design, and Code Generation. Deployment
    // and Testing still import fixtures directly; widen this glob to
    // src/features/* as each of those moves behind its own api seam.
    files: [
      "src/features/requirements/components/**/*.{ts,tsx}",
      "src/features/code-generation/components/**/*.{ts,tsx}",
    ],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["**/fixtures/*", "**/fixtures/**", "@/features/*/fixtures/*"],
              message: "Components call api/ modules; fixtures live behind the api seam.",
            },
          ],
        },
      ],
    },
  },
  {
    files: ["src/shared/**/*.{ts,tsx}", "src/lib/**/*.{ts,tsx}", "src/entities/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@/features/*", "@/features/*/*", "@/features/*/**", "@/app/*", "@/app/*/*"],
              message: "shared/, lib/, and entities/ must not import features or app.",
            },
          ],
        },
      ],
    },
  },
);
