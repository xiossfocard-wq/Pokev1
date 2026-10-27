"use client";

import { useState } from "react";
import { CARDNEXUS_URL, type Verification } from "@/lib/verifier";

/**
 * « Vérifier sur Cardmarket » et « CardNexus » : deux avis extérieurs sur
 * une carte, pour se faire le sien.
 *
 * CardNexus n'a pas d'adresse de recherche publique : le bouton copie la
 * recherche (nom et code) et ouvre sa page One Piece, où il n'y a plus qu'à
 * la coller.
 */
export default function LiensVerification({
  verification,
  classeBouton,
}: {
  verification: Verification;
  classeBouton: string;
}) {
  const [copie, setCopie] = useState<"ok" | "echec" | null>(null);
  const { cardmarketUrl, cardmarketTexte, version, cardnexusTexte } = verification;

  async function copier() {
    try {
      await navigator.clipboard.writeText(cardnexusTexte);
      setCopie("ok");
    } catch {
      setCopie("echec");
    }
  }

  return (
    <>
      <a
        href={cardmarketUrl}
        target="_blank"
        rel="noopener noreferrer"
        className={classeBouton}
        title={`Recherche « ${cardmarketTexte} »${
          version
            ? ` : Cardmarket liste toutes les versions et rééditions de ce code, choisis « (${version}) » dans l'édition d'origine.${
                version === "V.1" ? " Une carte sans illustration alternative n'a pas de mention de version." : ""
              }`
            : ""
        }`}
      >
        Vérifier sur Cardmarket{version ? ` (${version})` : ""} ↗
      </a>
      <a
        href={CARDNEXUS_URL}
        target="_blank"
        rel="noopener noreferrer"
        onClick={copier}
        className={classeBouton}
        title={`Copie « ${cardnexusTexte} » et ouvre CardNexus : colle-le dans sa recherche`}
      >
        CardNexus ↗
      </a>
      {copie && (
        <p className="order-last basis-full text-[11px] leading-snug text-ink-400">
          {copie === "ok" ? (
            <>
              « <span className="text-parchment-100">{cardnexusTexte}</span> » copié : colle-le dans la recherche
              CardNexus.
            </>
          ) : (
            <>
              Copie impossible : cherche « <span className="text-parchment-100">{cardnexusTexte}</span> » sur
              CardNexus.
            </>
          )}
        </p>
      )}
    </>
  );
}
