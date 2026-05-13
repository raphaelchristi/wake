/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  typedRoutes: false,
  // Hand the API base to client code via NEXT_PUBLIC_* so it lives in the
  // build output and is overridable at deploy time.
  env: {
    NEXT_PUBLIC_WAKE_API_BASE: process.env.NEXT_PUBLIC_WAKE_API_BASE ?? "http://localhost:8080",
  },
};

export default nextConfig;
