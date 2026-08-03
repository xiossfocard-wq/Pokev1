/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    // Photos d'annonces Vinted/eBay hébergées sur leurs CDN respectifs.
    remotePatterns: [
      { protocol: "https", hostname: "images1.vinted.net" },
      { protocol: "https", hostname: "images.vinted.net" },
      { protocol: "https", hostname: "i.ebayimg.com" },
    ],
  },
};

module.exports = nextConfig;
