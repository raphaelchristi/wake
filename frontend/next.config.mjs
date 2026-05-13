/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  experimental: {
    typedRoutes: false,
  },
  env: {
    NEXT_PUBLIC_WAKE_API_BASE:
      process.env.NEXT_PUBLIC_WAKE_API_BASE ?? "http://localhost:8080",
  },
};

export default nextConfig;
