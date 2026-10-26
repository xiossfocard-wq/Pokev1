"use client";

import { useState } from "react";
import Link from "next/link";
import FormulaireExemplaire from "./FormulaireExemplaire";
import { ajouterExemplaire } from "@/lib/api";

/** Sur la fiche d'une carte : combien d'exemplaires on en a, et en ranger un. */
export default function CollectionCarte({ cardId, initial }: { cardId: number; initial: number }) {
  const [exemplaires, setExemplaires] = useState(initial);
  const [ajout, setAjout] = useState(false);

  return (
    <div
      className={`rounded-md border p-3 ${
        exemplaires > 0 ? "border-moss-500/40 bg-moss-500/5" : "border-ink-700 bg-ink-800/60"
      }`}
    >
      {ajout ? (
        <FormulaireExemplaire
          libelle="Ranger dans ma collection"
          onAnnuler={() => setAjout(false)}
          onValider={async (prix, etat) => {
            const r = await ajouterExemplaire({ card_id: cardId, prix_paye: prix, etat });
            setExemplaires(r.exemplaires);
            setAjout(false);
          }}
        />
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <p className="flex-1 text-xs text-parchment-100/65">
            {exemplaires > 0 ? (
              <>
                <span className="text-moss-400">
                  ✓ Dans ta{" "}
                  <Link href="/collection" className="underline decoration-moss-500/40 underline-offset-2">
                    collection
                  </Link>
                </span>{" "}
                · {exemplaires} exemplaire{exemplaires > 1 ? "s" : ""}
              </>
            ) : (
              "Tu l'as déjà ? Range-la : sa valeur sera suivie avec le reste de ta collection."
            )}
          </p>
          <button
            type="button"
            onClick={() => setAjout(true)}
            className="rounded-md border border-moss-500/50 bg-moss-500/10 px-2.5 py-1 text-xs font-medium text-moss-400 transition-colors hover:bg-moss-500/20"
          >
            {exemplaires > 0 ? "＋ Un autre exemplaire" : "＋ J'ai cette carte"}
          </button>
        </div>
      )}
    </div>
  );
}
