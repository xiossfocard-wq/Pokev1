/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    remotePatterns: [
      // Photos d'annonces Vinted/eBay hébergées sur leurs CDN respectifs.
      { protocol: "https", hostname: "images1.vinted.net" },
      { protocol: "https", hostname: "images.vinted.net" },
      { protocol: "https", hostname: "i.ebayimg.com" },
      // Visuels officiels des cartes, via TCGdex (voir
      // backend/app/collectors/card_images.py).
      { protocol: "https", hostname: "assets.tcgdex.net" },
    ],
  },
};

module.exports = nextConfig;
