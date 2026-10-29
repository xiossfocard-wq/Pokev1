"use client";

import { useEffect, useState } from "react";
import { fetchAvisCardNexus, type AvisCardNexus } from "@/lib/api";
import { formatEur } from "@/lib/format";

/**
 * Ce que CardNexus dit de la carte : la moins chère de ses annonces en
 * Europe (et dans la langue de la carte), ses ventes des 30 derniers jours,
 * et l'écart avec notre cote. Rien du tout sans clé CardNexus.
 */
export default function BlocCardNexus({
  cardId,
  cote,
  langue,
}: {
  cardId: number;
  cote: number | null;
  langue: string | null;
}) {
  const [avis, setAvis] = useState<AvisCardNexus | null>(null);
  const [erreur, setErreur] = useState(false);

  useEffect(() => {
    let annule = false;
    setAvis(null);
    setErreur(false);
    fetchAvisCardNexus(cardId)
      .then((a) => !annule && setAvis(a))
      .catch(() => !annule && setErreur(true));
    return () => {
      annule = true;
    };
  }, [cardId]);

  if (erreur || (avis && !avis.configure)) return null;

  const titre = (
    <p className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-400">Sur CardNexus</p>
  );
  if (!avis) {
    return (
      <div className="rounded-md border border-ink-700 bg-ink-800/60 p-3">
        {titre}
        <p className="text-[11px] text-ink-400">Interrogation de CardNexus…</p>
      </div>
    );
  }
  if (!avis.trouve) {
    return (
      <div className="rounded-md border border-ink-700 bg-ink-800/60 p-3">
        {titre}
        <p className="text-[11px] text-ink-400">{avis.raison}</p>
      </div>
    );
  }

  const e = avis.europe;
  const nomLangue = langue === "fr" ? "en français" : langue === "en" ? "en anglais" : null;
  // Le prix qui se compare à notre cote : dans la langue de la carte si CardNexus le détaille.
  const reference = e?.plus_bas_langue ?? e?.plus_bas ?? null;
  const ecart = reference !== null && cote ? reference / cote - 1 : null;

  return (
    <div className="rounded-md border border-ink-700 bg-ink-800/60 p-3">
      {titre}
      <ul className="flex list-none flex-col gap-1 p-0 text-xs text-parchment-100/85">
        <li>
          Annonces en Europe :{" "}
          {e && e.plus_bas !== null ? (
            <>
              dès <span className="tabular font-mono text-parchment-100">{formatEur(e.plus_bas)}</span> ({e.annonces}{" "}
              annonce{e.annonces > 1 ? "s" : ""})
            </>
          ) : (
            <span className="text-ink-400">aucune en ce moment</span>
          )}
        </li>
        {nomLangue && e && e.plus_bas_langue !== null && (
          <li>
            {nomLangue[0].toUpperCase() + nomLangue.slice(1)} : dès{" "}
            <span className="tabular font-mono text-parchment-100">{formatEur(e.plus_bas_langue)}</span> (
            {e.annonces_langue} annonce{e.annonces_langue > 1 ? "s" : ""})
          </li>
        )}
        <li>
          Ventes conclues sur 30 jours :{" "}
          {avis.ventes_30j ? (
            <>
              {avis.ventes_30j}
              {avis.ventes_plus ? "+" : ""}
              {avis.ventes_mediane != null && (
                <>
                  , prix médian{" "}
                  <span className="tabular font-mono text-parchment-100">{formatEur(avis.ventes_mediane)}</span>
                </>
              )}
            </>
          ) : (
            <span className="text-ink-400">aucune</span>
          )}
        </li>
      </ul>
      {ecart !== null && Math.abs(ecart) >= 0.2 && (
        <p className={`mt-1.5 text-[11px] leading-snug ${ecart < 0 ? "text-moss-400" : "text-ink-400"}`}>
          {ecart < 0
            ? `${Math.round(-ecart * 100)} % sous notre cote : à vérifier (état, langue, version) avant d'y voir une affaire.`
            : `${Math.round(ecart * 100)} % au-dessus de notre cote : peu d'offres, ou une cote en retard.`}
        </p>
      )}
      {avis.url && (
        <a
          href={avis.url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 inline-block text-[11px] text-ember-400 underline decoration-ember-500/40 underline-offset-2"
          title={`${avis.nom} · ${avis.extension}`}
        >
          Voir la carte sur CardNexus ↗
        </a>
      )}
    </div>
  );
}
