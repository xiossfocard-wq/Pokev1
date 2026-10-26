"use client";

import type { SortField, SortOrder } from "@/lib/api";
import { useModeEvaluation } from "@/lib/mode";

interface SortBarProps {
  sortBy: SortField;
  order: SortOrder;
  onChange: (sortBy: SortField, order: SortOrder) => void;
}

export default function SortBar({ sortBy, order, onChange }: SortBarProps) {
  // En mode collection, on trie sur l'économie par rapport à la cote, pas
  // sur une marge de revente qu'on ne touchera pas.
  const mode = useModeEvaluation();
  const FIELDS: { value: SortField; label: string }[] = [
    { value: "deal_score", label: "Score" },
    mode === "collection"
      ? { value: "savings_eur", label: "Économie" }
      : { value: "margin_net", label: "Marge" },
    { value: "price", label: "Prix" },
    { value: "first_seen_at", label: "Date" },
  ];
  return (
    <div className="flex items-center gap-1 text-xs">
      {FIELDS.map((f) => {
        const active = f.value === sortBy;
        return (
          <button
            key={f.value}
            onClick={() => onChange(f.value, active && order === "desc" ? "asc" : "desc")}
            className={`rounded-sm px-2 py-1 font-mono transition-colors ${
              active
                ? "bg-ember-500/20 text-ember-400"
                : "text-ink-400 hover:text-parchment-100"
            }`}
          >
            {f.label}
            {active ? (order === "desc" ? " ↓" : " ↑") : ""}
          </button>
        );
      })}
    </div>
  );
}
