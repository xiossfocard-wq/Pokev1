"use client";

import { useEffect, useState } from "react";
import { fetchSettings, type ModeEvaluation } from "@/lib/api";

/**
 * Le mode d'évaluation choisi dans les réglages, partagé par tous les
 * composants qui affichent une affaire (radar, tri, catalogue). Lu une seule
 * fois par chargement de page ; la page Réglages le met à jour quand on
 * enregistre, sans attendre un rechargement.
 */
let enCache: ModeEvaluation | null = null;
let enCours: Promise<ModeEvaluation> | null = null;
const abonnes = new Set<(mode: ModeEvaluation) => void>();

export function definirMode(mode: ModeEvaluation) {
  enCache = mode;
  abonnes.forEach((prevenir) => prevenir(mode));
}

export function useModeEvaluation(): ModeEvaluation {
  // « collection » en attendant la réponse : c'est le défaut du serveur.
  const [mode, setMode] = useState<ModeEvaluation>(enCache ?? "collection");
  useEffect(() => {
    abonnes.add(setMode);
    if (enCache === null) {
      enCours ??= fetchSettings()
        .then((s) => s.mode_evaluation ?? "collection")
        .catch((): ModeEvaluation => "collection");
      enCours.then(definirMode);
    }
    return () => {
      abonnes.delete(setMode);
    };
  }, []);
  return mode;
}
