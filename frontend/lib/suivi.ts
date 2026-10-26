"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchCartesSuivies, nePlusSuivreCarte, suivreCarte, type CarteSuivie } from "@/lib/api";

/**
 * « Ma liste », partagée par le radar, le catalogue et la page Ma liste.
 * Chargée une fois par page ; suivre ou retirer une carte la recharge et
 * prévient tous les composants, pour que l'étoile apparaisse partout à la
 * fois.
 */
let enCache: CarteSuivie[] | null = null;
let enCours: Promise<CarteSuivie[]> | null = null;
const abonnes = new Set<(liste: CarteSuivie[]) => void>();

function publier(liste: CarteSuivie[]) {
  enCache = liste;
  abonnes.forEach((prevenir) => prevenir(liste));
}

export async function rechargerListe(): Promise<CarteSuivie[]> {
  enCours = fetchCartesSuivies();
  const liste = await enCours;
  publier(liste);
  return liste;
}

export async function suivre(cardId: number, prixMax: number | null) {
  await suivreCarte(cardId, prixMax);
  return rechargerListe();
}

export async function retirer(cardId: number) {
  await nePlusSuivreCarte(cardId);
  return rechargerListe();
}

export function useCartesSuivies() {
  const [liste, setListe] = useState<CarteSuivie[] | null>(enCache);
  useEffect(() => {
    abonnes.add(setListe);
    if (enCache === null) {
      enCours ??= fetchCartesSuivies();
      // Liste injoignable : on n'affiche simplement aucune étoile, le radar
      // reste utilisable.
      enCours.then(publier).catch(() => publier([]));
    }
    return () => {
      abonnes.delete(setListe);
    };
  }, []);
  // id de la fiche -> budget (null = suivie sans budget).
  const budgets = useMemo(
    () => new Map((liste ?? []).filter((e) => e.id !== null).map((e) => [e.id as number, e.prix_max])),
    [liste]
  );
  return { liste, budgets };
}

/** Le coût d'une annonce tombe-t-il dans le budget ? Jamais pour un lot. */
export function dansLeBudget(
  prixMax: number | null | undefined,
  cout: number,
  nonComparable?: string | null
): boolean {
  return prixMax != null && cout <= prixMax && !(nonComparable ?? "").startsWith("Lot");
}
