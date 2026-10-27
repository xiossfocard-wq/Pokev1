"use client";

import { useState } from "react";
import VisuelCarte from "./VisuelCarte";
import type { CartePersonnage } from "@/lib/api";
import { formatEur } from "@/lib/format";
import { suivre, useCartesSuivies } from "@/lib/suivi";

/**
 * Une carte d'un personnage : son visuel en grand, sa version, sa cote, ce
 * qu'on en a, et de quoi la suivre. Le titre perd « (Parallèle 1) » : la
 * version est dite juste en dessous.
 */
export default function TuileCarte({ carte, onOuvrir }: { carte: CartePersonnage; onOuvrir: (id: number) => void }) {
  const { budgets } = useCartesSuivies();
  const suivie = carte.suivie || budgets.has(carte.id);
  const [occupe, setOccupe] = useState(false);
  const hausse = Math.max(carte.variation_7j ?? 0, carte.variation_30j ?? 0);

  return (
    <li
      className={`flex flex-col overflow-hidden rounded-md border bg-ink-900 ${
        carte.exemplaires > 0 ? "border-moss-500/50" : "border-ink-700"
      }`}
    >
      <button
        type="button"
        onClick={() => onOuvrir(carte.id)}
        className="relative aspect-[63/88] w-full bg-ink-950"
        aria-label={`Ouvrir la fiche de ${carte.display_name}`}
      >
        <VisuelCarte
          src={carte.image_url}
          alt={carte.display_name}
          sizes="(max-width: 640px) 45vw, (max-width: 1024px) 30vw, 200px"
          repli={() => (
            <span className="flex h-full items-center justify-center p-2 text-center text-[10px] text-ink-400">
              Visuel pas encore récupéré
            </span>
          )}
        />
        {carte.exemplaires > 0 && (
          <span className="absolute left-1.5 top-1.5 rounded-sm border border-moss-500/60 bg-ink-950/85 px-1.5 py-0.5 text-[10px] text-moss-400">
            ✓ {carte.exemplaires > 1 ? `${carte.exemplaires} exemplaires` : "dans ta collection"}
          </span>
        )}
      </button>
      <div className="flex flex-1 flex-col gap-1 p-2.5">
        <div className="flex items-baseline justify-between gap-2">
          <p className="text-xs font-medium capitalize text-parchment-100">{carte.version}</p>
          <p className="tabular shrink-0 font-mono text-sm text-parchment-100">
            {carte.price_eur ? formatEur(carte.price_eur) : "—"}
          </p>
        </div>
        <p className="text-[10px] text-ink-400">
          {carte.card_code}
          {carte.series_name ? ` · ${carte.series_name}` : ""}
        </p>
        <div className="flex flex-wrap gap-1">
          {carte.visuel && (
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                carte.belle
                  ? "bg-gradient-to-r from-fuchsia-500/20 to-amber-400/20 text-amber-200 ring-1 ring-amber-400/30"
                  : "bg-ink-700 text-parchment-100"
              }`}
            >
              {carte.visuel}
            </span>
          )}
          {carte.en_vente > 0 && (
            <span
              className="rounded bg-ember-500/15 px-1.5 py-0.5 text-[10px] font-medium text-ember-400"
              title="Annonces en vente en ce moment : ouvre la fiche pour les voir"
            >
              {carte.en_vente} en vente
            </span>
          )}
          {hausse >= 0.1 && (
            <span className="rounded bg-moss-500/20 px-1.5 py-0.5 text-[10px] font-medium text-moss-400">
              ▲ {Math.round(hausse * 100)} %
            </span>
          )}
        </div>
        <div className="mt-auto pt-1">
          <button
            type="button"
            disabled={suivie || occupe}
            onClick={async () => {
              setOccupe(true);
              try {
                await suivre(carte.id, carte.price_eur ? Math.ceil(carte.price_eur) : null);
              } finally {
                setOccupe(false);
              }
            }}
            className={`rounded-md border px-2 py-1 text-[11px] font-medium transition-colors ${
              suivie
                ? "border-amber-300/40 text-amber-200"
                : "border-amber-300/50 bg-amber-300/10 text-amber-200 hover:bg-amber-300/20"
            }`}
            title={suivie ? "Déjà dans ta liste" : "L'ajouter à Ma liste, avec la cote comme budget"}
          >
            {suivie ? "★ Suivie" : occupe ? "…" : "☆ Suivre"}
          </button>
        </div>
      </div>
    </li>
  );
}
