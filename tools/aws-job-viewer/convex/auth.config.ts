import type { AuthConfig } from "convex/server";

export default {
  providers: [
    {
      domain: "https://oidc.vercel.com/jlasters-projects",
      applicationID: "https://vercel.com/jlasters-projects",
    },
  ],
} satisfies AuthConfig;
