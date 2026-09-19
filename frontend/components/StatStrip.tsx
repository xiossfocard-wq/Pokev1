"use client";

import type { Listing, PriceIndexStatus } from "@/lib/api";

interface StatStripProps {
  listings: Listing[];
  indexStatus: PriceIndexStatus | null;
  dealThreshold: number;
  loading: boolean;
}

function minutesSince(iso: string): number {
  return Math.floor((Date.now() - new Date(iso + "Z").getTime()) / 60000);
}

function formatAge(minutes: number): string {
  if (minutes < 1) return "à l'instant";
  if (minutes < 60) return `il y a ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `il y a ${hours} h`;
  return `il y a ${Math.floor(hours / 24)} j`;
}

/**
 * Quatre chiffres qui disent l'état du radar avant même de lire une carte :
 * combien d'affaires dépassent le seuil, combien d'annonces sont suivies,
 * où en est l'index de prix, et quand la dernière collecte a eu lieu.
 *
 * Le dernier est le plus important : l'hébergement gratuit endort le
 * serveur, et une collecte vieille de 13 heures change complètement la
 * lecture des scores. Un point vert qui respire signale une collecte de
 * moins de 30 minutes.
 */
export default function StatStrip({ listings, indexStatus, dealThreshold, loading }: StatStripProps) {
  const deals = listings.filter((l) => (l.deal_score ?? 0) >= dealThreshold).length;
  const reliable = listings.filter(
    (l) => l.price_match_confidence === "high" || l.price_match_confidence === "manual"
  ).length;

  const newest = listings.reduce<string | null>(
    (acc, l) => (acc === null || l.first_seen_at > acc ? l.first_seen_at : acc),
    null
  );
  const ageMinutes = newest ? minutesSince(newest) : null;
  const isFresh = ageMinutes !== null && ageMinutes < 30;

  const tiles = [
    {
      label: "Bonnes affaires",
      value: loading ? null : String(deals),
      hint: `score ≥ ${dealThreshold}`,
      tone: deals > 0 ? "text-moss-400" : "text-parchment-100",
      live: false,
    },
    {
      label: "Prix fiables",
      value: loading ? null : `${reliable}/${listings.length}`,
      hint: "identifiées précisément",
      tone: "text-parchment-100",
      live: false,
    },
    {
      label: "Index des prix",
      value: indexStatus ? `${Math.round(indexStatus.progress_percent)} %` : null,
      hint: indexStatus
        ? `${indexStatus.cards_in_index.toLocaleString("fr-FR")} cartes · ${indexStatus.series_synced}/${indexStatus.series_known} séries`
        : "",
      tone: indexStatus && indexStatus.progress_percent >= 99 ? "text-moss-400" : "text-ember-400",
      live: false,
    },
    {
      label: "Dernière collecte",
      value: loading ? null : ageMinutes === null ? "—" : formatAge(ageMinutes),
      hint: isFresh ? "le radar est actif" : "réveillé à l'ouverture de la page",
      tone: isFresh ? "text-moss-400" : "text-parchment-100",
      live: isFresh,
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
      {tiles.map((t) => (
        <div
          key={t.label}
          className="rounded-lg border border-ink-700 bg-ink-800/60 px-3.5 py-3 backdrop-blur-sm"
        >
          <div className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-600">
            {t.live && <span className="live-dot h-1.5 w-1.5 rounded-full bg-moss-400" />}
            {t.label}
          </div>
          {t.value === null ? (
            <div className="skeleton mt-1.5 h-6 w-16" />
          ) : (
            <div className={`tabular mt-1 font-display text-2xl leading-none ${t.tone}`}>
              {t.value}
            </div>
          )}
          <div className="mt-1 truncate text-[11px] text-ink-600">{t.hint}</div>
        </div>
      ))}
    </div>
  );
}
