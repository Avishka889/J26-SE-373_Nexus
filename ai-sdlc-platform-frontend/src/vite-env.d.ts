/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string;
  readonly VITE_LIVE_FEATURES?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
