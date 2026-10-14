// Renseigner NEXT_PUBLIC_CARD_IMAGE_HOST (le nom d'hote seul, sans
// schema ni chemin) si CARD_IMAGE_BASE_URL pointe ailleurs que sur le site
// officiel du jeu.
const hoteImagesSupplementaire = process.env.NEXT_PUBLIC_CARD_IMAGE_HOST;

/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    remotePatterns: [
      // Photos d'annonces Vinted/eBay hébergées sur leurs CDN respectifs.
      // Caractère générique volontaire : Vinted répartit ses photos sur
      // images1, images2, images3… Deux sous-domaines écrits en dur
      // faisaient échouer next/image sur tous les autres, donc perdre
      // justement la photo qu'on regarde avant d'acheter.
      { protocol: "https", hostname: "*.vinted.net" },
      { protocol: "https", hostname: "*.ebayimg.com" },
      // Illustrations officielles des cartes One Piece (voir
      // backend/app/collectors/card_images.py).
      { protocol: "https", hostname: "en.onepiece-cardgame.com" },
      // L'hote des illustrations est configurable cote backend
      // (CARD_IMAGE_BASE_URL). Sans cette entree, en changer cote backend
      // ferait echouer next/image ici, et le lien entre les deux reglages
      // serait tres difficile a retrouver.
      ...(hoteImagesSupplementaire
        ? [{ protocol: "https", hostname: hoteImagesSupplementaire }]
        : []),
    ],
  },
};

module.exports = nextConfig;
