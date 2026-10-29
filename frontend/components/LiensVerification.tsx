"use client";

import { useState } from "react";
import { fetchLienCardNexus } from "@/lib/api";
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

  // L'onglet s'ouvre tout de suite (sinon le navigateur bloque la fenêtre),
  // puis va sur la page de la carte quand le serveur l'a trouvée via l'API
  // CardNexus. Faute de page trouvée : la recherche est copiée, à coller.
  async function ouvrirCardNexus(e: React.MouseEvent) {
    e.preventDefault();
    const onglet = window.open("about:blank", "_blank");
    let url: string | null = null;
    try {
      url = (await fetchLienCardNexus(verification.cardnexus)).url;
    } catch {
      url = null;
    }
    if (!url) await copier();
    if (onglet) {
      onglet.opener = null; // la page ouverte ne peut pas agir sur la nôtre
      onglet.location.href = url ?? CARDNEXUS_URL;
    }
    else window.open(url ?? CARDNEXUS_URL, "_blank", "noopener");
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
        onClick={ouvrirCardNexus}
        className={classeBouton}
        title={`Ouvre la page de la carte sur CardNexus (sinon, copie « ${cardnexusTexte} » à coller dans sa recherche)`}
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
