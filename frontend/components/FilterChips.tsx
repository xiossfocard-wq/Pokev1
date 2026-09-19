"use client";

import type { ListingSource } from "@/lib/api";

export type SourceFilter = "all" | ListingSource;
export type ConfidenceFilter = "all" | "reliable" | "probable" | "uncertain";

export interface Filters {
  source: SourceFilter;
  confidence: ConfidenceFilter;
  minScore: number;
}

export const DEFAULT_FILTERS: Filters = { source: "all", confidence: "all", minScore: 0 };

interface FilterChipsProps {
  value: Filters;
  onChange: (next: Filters) => void;
}

interface ChipGroupProps<T extends string | number> {
  label: string;
  options: { value: T; label: string }[];
  selected: T;
  onSelect: (value: T) => void;
}

function ChipGroup<T extends string | number>({ label, options, selected, onSelect }: ChipGroupProps<T>) {
  return (
    <div className="flex items-center gap-1.5" role="group" aria-label={label}>
      <span className="mr-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-600">
        {label}
      </span>
      {options.map((o) => {
        const active = o.value === selected;
        return (
          <button
            key={String(o.value)}
            type="button"
            aria-pressed={active}
            onClick={() => onSelect(o.value)}
            className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
              active
                ? "border-ember-500/60 bg-ember-500/15 text-ember-400"
                : "border-ink-700 text-ink-600 hover:border-ink-600 hover:text-parchment-100"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Filtres en puces, appliqués côté navigateur sur les annonces déjà
 * chargées : instantané, sans aller-retour serveur.
 *
 * « Fiabilité » est le filtre qui compte le plus pour l'usage réel :
 * ne montrer que les prix identifiés précisément, c'est ne regarder que
 * les annonces où le chiffre affiché veut vraiment dire quelque chose.
 */
export default function FilterChips({ value, onChange }: FilterChipsProps) {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
      <ChipGroup<SourceFilter>
        label="Source"
        selected={value.source}
        onSelect={(source) => onChange({ ...value, source })}
        options={[
          { value: "all", label: "Tout" },
          { value: "vinted", label: "Vinted" },
          { value: "ebay", label: "eBay" },
        ]}
      />
      <ChipGroup<ConfidenceFilter>
        label="Fiabilité"
        selected={value.confidence}
        onSelect={(confidence) => onChange({ ...value, confidence })}
        options={[
          { value: "all", label: "Toutes" },
          { value: "reliable", label: "Fiable" },
          { value: "probable", label: "Probable" },
          { value: "uncertain", label: "Incertain" },
        ]}
      />
      <ChipGroup<number>
        label="Score"
        selected={value.minScore}
        onSelect={(minScore) => onChange({ ...value, minScore })}
        options={[
          { value: 0, label: "Tous" },
          { value: 50, label: "≥ 50" },
          { value: 70, label: "≥ 70" },
          { value: 85, label: "≥ 85" },
        ]}
      />
    </div>
  );
}

/** Applique les filtres à une liste. Pure : aucune mutation. */
export function applyFilters<T extends {
  source: ListingSource;
  deal_score: number | null;
  price_match_confidence: string | null;
}>(items: T[], filters: Filters): T[] {
  return items.filter((l) => {
    if (filters.source !== "all" && l.source !== filters.source) return false;
    if ((l.deal_score ?? 0) < filters.minScore) return false;

    const c = l.price_match_confidence;
    switch (filters.confidence) {
      case "reliable":
        return c === "high" || c === "manual";
      case "probable":
        return c === "medium";
      case "uncertain":
        return c === "low" || c === null;
      default:
        return true;
    }
  });
}
