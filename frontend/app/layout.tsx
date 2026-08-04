import type { Metadata } from "next";
import { Fraunces, Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--font-display",
  weight: ["500", "600"],
});
const inter = Inter({ subsets: ["latin"], variable: "--font-body" });
const jetbrainsMono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "Le Pokéradar à Pépites",
  description:
    "Surveillance Vinted & eBay pour cartes Pokémon françaises, comparée à Cardmarket et ZebraDex.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <body className={`${fraunces.variable} ${inter.variable} ${jetbrainsMono.variable} font-body`}>
        {children}
      </body>
    </html>
  );
}
