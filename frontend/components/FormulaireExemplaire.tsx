"use client";

import { useState } from "react";
import type { Etat } from "@/lib/api";

const ETATS: { valeur: Etat | ""; libelle: string }[] = [
  { valeur: "", libelle: "État inconnu" },
  { valeur: "NM", libelle: "NM — comme neuve" },
  { valeur: "LP", libelle: "LP — légères traces" },
  { valeur: "MP", libelle: "MP — usure visible" },
  { valeur: "HP", libelle: "HP — très abîmée" },
  { valeur: "DMG", libelle: "DMG — endommagée" },
];

/**
 * Prix payé et état d'un exemplaire, avant de le ranger dans la collection.
 * Les deux sont facultatifs : un exemplaire sans prix payé compte dans la
 * valeur, pas dans la plus-value ; un état inconnu ne décote pas.
 */
export default function FormulaireExemplaire({
  prixInitial,
  etatInitial,
  libelle,
  onValider,
  onAnnuler,
}: {
  prixInitial?: number | null;
  etatInitial?: Etat | null;
  libelle: string;
  onValider: (prix: number | null, etat: Etat | null) => Promise<void>;
  onAnnuler: () => void;
}) {
  const [prix, setPrix] = useState(prixInitial != null ? String(prixInitial).replace(".", ",") : "");
  const [etat, setEtat] = useState<Etat | "">(etatInitial ?? "");
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  async function valider(e: React.FormEvent) {
    e.preventDefault();
    const texte = prix.trim().replace(",", ".");
    const valeur = texte === "" ? null : Number(texte);
    if (valeur !== null && (!Number.isFinite(valeur) || valeur < 0)) {
      setErreur("Indique un prix positif, ou laisse vide.");
      return;
    }
    setOccupe(true);
    setErreur(null);
    try {
      await onValider(valeur, etat === "" ? null : etat);
    } catch (err) {
      setErreur(err instanceof Error ? err.message : String(err));
    } finally {
      setOccupe(false);
    }
  }

  return (
    <form onSubmit={valider} className="flex flex-col gap-2">
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-[11px] text-ink-400">
          Prix payé, frais compris (€)
          <input
            type="text"
            inputMode="decimal"
            value={prix}
            onChange={(e) => setPrix(e.target.value)}
            autoFocus
            placeholder="facultatif"
            className="tabular mt-0.5 block w-28 rounded-md border border-ink-700 bg-ink-900 px-2.5 py-1.5 font-mono text-sm text-parchment-100 placeholder:text-ink-400 focus:border-moss-400 focus:outline-none"
          />
        </label>
        <label className="text-[11px] text-ink-400">
          État
          <select
            value={etat}
            onChange={(e) => setEtat(e.target.value as Etat | "")}
            className="mt-0.5 block rounded-md border border-ink-700 bg-ink-900 px-2 py-1.5 text-sm text-parchment-100 focus:border-moss-400 focus:outline-none"
          >
            {ETATS.map((o) => (
              <option key={o.valeur} value={o.valeur}>
                {o.libelle}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={occupe}
          className="rounded-md bg-moss-400/90 px-3 py-1.5 text-xs font-medium text-ink-950 transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {occupe ? "…" : libelle}
        </button>
        <button
          type="button"
          onClick={onAnnuler}
          className="rounded-md border border-ink-700 px-2.5 py-1.5 text-xs text-ink-400 hover:text-parchment-100"
        >
          Annuler
        </button>
      </div>
      {erreur && <p className="text-[11px] text-rust-400">{erreur}</p>}
    </form>
  );
}
