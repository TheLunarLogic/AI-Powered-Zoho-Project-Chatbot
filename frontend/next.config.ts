import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/:path*",
      },
      {
        source: "/auth/:path*",
        destination: "http://localhost:8000/auth/:path*",
      },
    ];
  },
};

export default nextConfig;
