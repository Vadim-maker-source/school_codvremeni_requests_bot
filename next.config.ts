import type { NextConfig } from 'next';
const nextConfig: NextConfig = { output: 'standalone', devIndicators: false, distDir: process.env.NEXT_DIST_DIR || '.next', async rewrites() { return [{source:'/api/:path*',destination:`${process.env.API_INTERNAL_URL || 'http://127.0.0.1:8000'}/api/:path*`}]; } };
export default nextConfig;
