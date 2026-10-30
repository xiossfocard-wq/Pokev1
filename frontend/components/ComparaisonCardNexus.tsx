"use client";

import { useState } from "react";
import { fetchAvisCardNexus, type AvisCardNexus } from "@/lib/api";
import { formatEur } from "@/lib/format";

/**
 * Une annonce face au marché CardNexus : est-elle moins chère que la moins
 * chère de ses offres en Europe ? Interrogé seulement sur demande : le
 * panneau existe pour chaque annonce de la liste, et l'API compte les
 * requêtes.
 */
export default function ComparaisonCardNexus({
  cardId,
  cout,
  classeBouton,
}: {
  cardId: number;
  /** Ce que l'annonce coûte vraiment (protection et port compris). */
  cout: number;
  classeBouton: string;
}) {
  const [etat, setEtat] = useState<"repos" | "attente" | "erreur">("repos");
  const [avis, setAvis] = useState<AvisCardNexus | null>(null);

  async function comparer() {
    setEtat("attente");
    try {
      setAvis(await fetchAvisCardNexus(cardId));
      setEtat("repos");
    } catch {
      setEtat("erreur");
    }
  }

  if (!avis) {
    return (
      <div className="basis-full">
        <button type="button" onClick={comparer} disabled={etat === "attente"} className={classeBouton}>
          {etat === "attente" ? "Comparaison…" : "Comparer avec CardNexus"}
        </button>
        {etat === "erreur" && <p className="mt-1 text-[11px] text-rust-400">CardNexus n&apos;a pas répondu.</p>}
      </div>
    );
  }

  let texte: React.ReactNode;
  if (!avis.configure) texte = "CardNexus n'est pas configuré (clé CARDNEXUS_API_KEY).";
  else if (!avis.trouve) texte = avis.raison;
  else {
    const e = avis.europe;
    const reference = e?.plus_bas_langue ?? e?.plus_bas ?? null;
    if (reference === null) {
      texte = "Aucune offre CardNexus en Europe en ce moment : rien à comparer.";
    } else {
      const ecart = reference - cout;
      texte = (
        <>
          Moins chère sur CardNexus{e?.plus_bas_langue != null ? " (même langue)" : ""} :{" "}
          <span className="tabular font-mono text-parchment-100">{formatEur(reference)}</span>, hors port.{" "}
          <span className={ecart > 0 ? "text-moss-400" : "text-ink-400"}>
            {ecart > 0
              ? `Cette annonce coûte ${formatEur(ecart)} de moins, tout compris.`
              : `Cette annonce coûte ${formatEur(-ecart)} de plus, tout compris.`}
          </span>
        </>
      );
    }
  }

  return (
    <p className="basis-full text-[11px] leading-snug text-ink-400">
      {texte}
      {avis.url && (
        <>
          {" "}
          <a href={avis.url} target="_blank" rel="noopener noreferrer" className="text-ember-400 underline underline-offset-2">
            Voir ↗
          </a>
        </>
      )}
    </p>
  );
}
