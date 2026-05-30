/// <reference types="vite/client" />

// Typed environment variables — extend as new VITE_* vars are added.
interface ImportMetaEnv {
  readonly VITE_API_URL?: string
}
interface ImportMeta {
  readonly env: ImportMetaEnv
}
