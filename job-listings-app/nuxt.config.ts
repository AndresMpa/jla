// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: "2024-11-01",
  devtools: { enabled: true },

  modules: [
    "@nuxtjs/tailwindcss",
    "shadcn-nuxt",
    "@nuxtjs/color-mode",
    "@nuxtjs/i18n",
  ],

  components: [
    {
      path: "~/components/ui",
      pathPrefix: false,
      pattern: "**/*.vue",
    },
    {
      path: "~/components",
      pathPrefix: true,
    },
  ],

  shadcn: {
    prefix: "",
    componentDir: "./components/ui",
  },

  i18n: {
    strategy: "prefix_except_default",
    defaultLocale: "en",
    locales: [
      { code: "en", iso: "en-US", name: "English", file: "en.json" },
      { code: "es", iso: "es-ES", name: "Español", file: "es.json" },
    ],
    langDir: "locales/",
  },

  routeRules: {
    "/": { prerender: true, redirect: "/home" },
    "/home": { ssr: true },
    "/profiles": { ssr: false },
    "/jobs": { ssr: false },
    "/jobs/**": { ssr: false },
    "/about": { ssr: true, redirect: "/jobs" },
    "/settings": { ssr: false },
  },

  runtimeConfig: {
    backendUrl: process.env.NUXT_BACKEND_URL || "http://localhost:8000",
    public: {
      // The browser needs a URL it can actually reach directly for the
      // WebSocket progress streams (WS /ws/run/status, WS
      // /ws/jobs/{id}/cv-status) - unlike backendUrl above, which is only
      // ever used server-side by Nitro's own routes and can safely point
      // at a docker-network-internal hostname like http://backend:8000.
      // Defaults to the same host the page was loaded from, on the
      // backend's exposed port, which matches this project's compose.yml
      // (BACKEND_PORT is published to the host, not just the container
      // network) without needing extra config for the common case.
      backendWsBase: process.env.NUXT_PUBLIC_BACKEND_WS_BASE || "",
      backendWsPort: process.env.NUXT_PUBLIC_BACKEND_WS_PORT || "8000",
    },
  },

  typescript: {
    typeCheck: true,
  },

  colorMode: {
    classSuffix: "",
    preference: "dark",
    fallback: "dark",
  },
});
