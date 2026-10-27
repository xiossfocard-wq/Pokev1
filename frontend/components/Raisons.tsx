import type { RaisonIdee } from "@/lib/api";

/** Une couleur par nature de raison : on lit d'un coup d'œil ce qui fait l'intérêt de la carte. */
export const STYLE_RAISON: Record<RaisonIdee["type"], string> = {
  gout: "bg-amber-300/20 text-amber-100 ring-1 ring-amber-300/50",
  visuel: "bg-gradient-to-r from-fuchsia-500/20 to-amber-400/20 text-amber-200 ring-1 ring-amber-400/30",
  personnage: "bg-sky-500/15 text-sky-300",
  tendance: "bg-moss-500/20 text-moss-400",
  "sous-cotee": "bg-ember-500/15 text-ember-400",
  vinted: "bg-ink-700 text-parchment-100",
  collection: "bg-amber-300/15 text-amber-200",
};

export default function Raisons({ raisons, sans = [] }: { raisons: RaisonIdee[]; sans?: RaisonIdee["type"][] }) {
  return (
    <div className="flex flex-wrap gap-1">
      {raisons
        .filter((r) => !sans.includes(r.type))
        .map((r) => (
          <span key={r.texte} className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${STYLE_RAISON[r.type]}`}>
            {r.texte}
          </span>
        ))}
    </div>
  );
}
