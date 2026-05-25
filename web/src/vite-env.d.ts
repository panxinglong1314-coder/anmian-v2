/// <reference types="vite/client" />
/// <reference types="vite-plugin-pwa/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_API_TARGET?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}

interface ImportMetaEnv {
  readonly VITE_GOOGLE_CLIENT_ID?: string;
}

// Google Identity Services (loaded via <script> at runtime)
interface Window {
  google?: {
    accounts: {
      id: {
        initialize: (config: {
          client_id: string;
          callback: (resp: { credential: string }) => void;
        }) => void;
        renderButton: (parent: HTMLElement | null, options: Record<string, unknown>) => void;
      };
    };
  };
}
