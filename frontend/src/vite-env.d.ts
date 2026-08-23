/// <reference types="vite/client" />

declare module "3dmol/build/3Dmol.es6.js";

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_SUPABASE_URL?: string;
  readonly VITE_SUPABASE_ANON_KEY?: string;
}
