"use client";

import { useState } from "react";
import Link from "next/link";
import { formatEur } from "@/lib/format";
import { retirer, suivre, useCartesSuivies } from "@/lib/suivi";

/**
 * Suivre une carte, avec un budget : le coût RÉEL maximum qu'on est prêt à
 * payer, protection acheteur et port compris. Une annonce sous ce budget
 * déclenche une alerte quel que soit son score, et ressort sur le radar.
 *
 * `initial` vient de la fiche de la carte : il sert tant que la liste
 * partagée n'est pas encore chargée, pour que le bouton ne clignote pas de
 * « Suivre » à « Suivie » à l'ouverture.
 */
export default function SuiviCarte({
  cardId,
  cote,
  initial,
}: {
  cardId: number;
  cote: number | null;
  initial: { prix_max: number | null } | null;
}) {
  const { liste, budgets } = useCartesSuivies();
  const suivie = liste === null ? initial !== null : budgets.has(cardId);
  const budget = liste === null ? initial?.prix_max ?? null : budgets.get(cardId) ?? null;

  const [edition, setEdition] = useState(false);
  const [saisie, setSaisie] = useState("");
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [vientDAjouter, setVientDAjouter] = useState(false);

  function ouvrir() {
    // Proposer la cote comme point de départ : c'est le prix auquel la carte
    // s'achète ailleurs, le budget se règle autour.
    const depart = budget ?? (cote !== null ? Math.ceil(cote) : null);
    setSaisie(depart !== null ? String(depart) : "");
    setEdition(true);
    setErreur(null);
  }

  async function enregistrer(e: React.FormEvent) {
    e.preventDefault();
    const texte = saisie.trim().replace(",", ".");
    const valeur = texte === "" ? null : Number(texte);
    if (valeur !== null && (!Number.isFinite(valeur) || valeur <= 0)) {
      setErreur("Indique un montant supérieur à 0, ou laisse vide pour suivre sans budget.");
      return;
    }
    setOccupe(true);
    try {
      const etaitSuivie = suivie;
      await suivre(cardId, valeur);
      setEdition(false);
      setErreur(null);
      setVientDAjouter(!etaitSuivie);
    } catch (err) {
      setErreur(err instanceof Error ? err.message : String(err));
    } finally {
      setOccupe(false);
    }
  }

  async function arreter() {
    setOccupe(true);
    try {
      await retirer(cardId);
      setEdition(false);
    } catch (err) {
      setErreur(err instanceof Error ? err.message : String(err));
    } finally {
      setOccupe(false);
    }
  }

  return (
    <div
      className={`rounded-md border p-3 ${
        suivie ? "border-amber-300/40 bg-amber-300/5" : "border-ink-700 bg-ink-800/60"
      }`}
    >
      {!edition && (
        <div className="flex flex-wrap items-center gap-2">
          {suivie ? (
            <p className="flex-1 text-xs text-amber-200">
              ★ Dans ta liste
              <span className="text-parchment-100/65">
                {budget !== null ? ` · budget ${formatEur(budget)} frais compris` : " · sans budget"}
              </span>
            </p>
          ) : (
            <p className="flex-1 text-xs text-parchment-100/65">
              Tu cherches cette carte ? Suis-la : tu seras prévenu dès qu&apos;une annonce passe sous ton budget.
            </p>
          )}
          <button
            type="button"
            onClick={ouvrir}
            disabled={occupe}
            className="rounded-md border border-amber-300/50 bg-amber-300/10 px-2.5 py-1 text-xs font-medium text-amber-200 transition-colors hover:bg-amber-300/20 disabled:opacity-40"
          >
            {suivie ? "Modifier le budget" : "☆ Suivre"}
          </button>
          {suivie && (
            <button
              type="button"
              onClick={arreter}
              disabled={occupe}
              className="rounded-md border border-ink-700 px-2.5 py-1 text-xs text-ink-400 transition-colors hover:text-parchment-100 disabled:opacity-40"
            >
              Retirer
            </button>
          )}
        </div>
      )}

      {edition && (
        <form onSubmit={enregistrer} className="flex flex-col gap-2">
          <label className="text-xs text-parchment-100">
            Budget maximum, protection acheteur et port compris (€)
            <span className="mt-0.5 block text-[11px] text-ink-400">
              Laisse vide pour suivre la carte sans alerte de prix.
              {cote !== null ? ` Cote actuelle : ${formatEur(cote)}.` : ""}
            </span>
          </label>
          <div className="flex gap-2">
            <input
              type="text"
              inputMode="decimal"
              value={saisie}
              onChange={(e) => setSaisie(e.target.value)}
              autoFocus
              aria-label="Budget maximum en euros"
              className="tabular w-28 rounded-md border border-ink-700 bg-ink-900 px-2.5 py-1.5 font-mono text-sm text-parchment-100 focus:border-amber-300 focus:outline-none"
            />
            <button
              type="submit"
              disabled={occupe}
              className="rounded-md bg-amber-300/90 px-3 py-1.5 text-xs font-medium text-ink-950 transition-opacity hover:opacity-90 disabled:opacity-40"
            >
              {occupe ? "…" : suivie ? "Enregistrer" : "Suivre"}
            </button>
            <button
              type="button"
              onClick={() => setEdition(false)}
              className="rounded-md border border-ink-700 px-2.5 py-1.5 text-xs text-ink-400 hover:text-parchment-100"
            >
              Annuler
            </button>
          </div>
        </form>
      )}

      {vientDAjouter && suivie && (
        <p className="mt-2 text-[11px] text-ink-400">
          Recherche lancée sur Vinted : les annonces trouvées apparaissent dans{" "}
          <Link href="/suivi" className="text-amber-200 underline decoration-amber-300/40 underline-offset-2">
            Ma liste
          </Link>{" "}
          d&apos;ici une minute.
        </p>
      )}
      {erreur && <p className="mt-2 text-[11px] text-rust-400">{erreur}</p>}
    </div>
  );
}
