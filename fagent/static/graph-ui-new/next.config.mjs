/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export: produces out/ directory served directly by Python backend
  output: 'export',
  trailingSlash: true,
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
}

export default nextConfig
