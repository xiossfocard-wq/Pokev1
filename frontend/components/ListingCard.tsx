import Image from "next/image";
import type { Listing } from "@/lib/api";
import DealScoreBadge from "./DealScoreBadge";

function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso + "Z").getTime();
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return "à l'instant";
  if (minutes < 60) return `il y a ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `il y a ${hours} h`;
  return `il y a ${Math.floor(hours / 24)} j`;
}

function formatEur(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("fr-FR", { style: "currency", currency: "EUR" });
}

const RARITY_STYLES: Record<string, string> = {
  "Special Illustration Rare": "bg-gradient-to-r from-fuchsia-500/25 to-amber-400/25 text-amber-200 ring-1 ring-amber-400/40",
  "Secret Illustration Rare": "bg-gradient-to-r from-fuchsia-500/25 to-amber-400/25 text-amber-200 ring-1 ring-amber-400/40",
  "Hyper Rare": "bg-gradient-to-r from-sky-400/25 to-fuchsia-500/25 text-sky-200 ring-1 ring-sky-400/40",
  "Illustration Rare": "bg-ember-500/20 text-ember-400 ring-1 ring-ember-500/40",
  "Shiny Ultra Rare": "bg-violet-500/20 text-violet-300 ring-1 ring-violet-400/30",
  "Ultra Rare": "bg-violet-500/15 text-violet-300",
  "Shiny Rare": "bg-cyan-500/15 text-cyan-300",
  "Double Rare": "bg-ink-700 text-parchment-100",
};

const CONDITION_STYLES: Record<string, string> = {
  NM: "bg-moss-500/20 text-moss-400",
  LP: "bg-ember-500/15 text-ember-400",
  MP: "bg-rust-500/15 text-rust-400",
  HP: "bg-rust-500/25 text-rust-400",
  DMG: "bg-rust-500/30 text-rust-400",
};

const CONFIDENCE_LABEL: Record<string, string> = {
  high: "Prix fiable — carte identifiée précisément",
  medium: "Prix probable — identification partielle",
  low: "Prix incertain — nom seul, plusieurs séries possibles",
};

export default function ListingCard({ listing }: { listing: Listing }) {
  const photo = listing.photo_urls?.[0];
  const marginPositive = (listing.margin_net ?? 0) > 0;
  const hasNoPrice = listing.reference_price === null;
  const hasRange = listing.price_low_eur != null && listing.price_high_eur != null;
  const confidence = listing.price_match_confidence;
  const detail = listing.price_detail;
  const priceWarning = detail?.warning ?? null;
  const ambiguousCount = detail?.candidates_count ?? 0;
  const spread = detail?.price_spread_eur ?? 0;
  const minPrice = detail?.candidates_min_eur ?? null;
  const maxPrice = detail?.candidates_max_eur ?? null;
  const searchUrl = `https://www.google.com/search?q=${encodeURIComponent(
    listing.title + " pokemon carte prix"
  )}`;

  return (
    <article className="group relative overflow-hidden rounded-lg border border-ink-700 bg-ink-800/80 transition-all hover:border-ember-500/50 hover:bg-ink-800">
      <a
        href={listing.url}
        target="_blank"
        rel="noopener noreferrer"
        className="flex gap-3 p-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ember-500"
      >
        <div className="relative h-24 w-[68px] shrink-0 overflow-hidden rounded-md bg-ink-700 ring-1 ring-ink-600">
          {photo ? (
            <Image src={photo} alt="" fill sizes="68px" className="object-cover" unoptimized />
          ) : (
            <div className="flex h-full items-center justify-center px-1 text-center text-[9px] text-ink-600">
              pas de photo
            </div>
          )}
        </div>

        <div className="min-w-0 flex-1">
          <p className="line-clamp-2 text-sm font-medium leading-snug text-parchment-100 group-hover:text-ember-400">
            {listing.title}
          </p>

          <div className="mt-1.5 flex flex-wrap gap-1">
            {listing.condition_tier && (
              <span
                className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                  CONDITION_STYLES[listing.condition_tier] ?? "bg-ink-700 text-ink-600"
                }`}
                title="État déduit du texte de l'annonce (NM > LP > MP > HP > DMG)"
              >
                {listing.condition_tier}
              </span>
            )}
            {listing.rarity_tier && (
              <span
                className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                  RARITY_STYLES[listing.rarity_tier] ?? "bg-ember-500/15 text-ember-400"
                }`}
              >
                {listing.rarity_tier}
              </span>
            )}
            {listing.is_vintage && (
              <span className="rounded bg-moss-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-moss-400">
                Vintage
              </span>
            )}
            {listing.is_popular_pokemon && (
              <span className="rounded bg-ink-700 px-1.5 py-0.5 text-[10px] font-semibold text-parchment-100">
                Populaire
              </span>
            )}
          </div>

          <div className="mt-2 flex flex-wrap items-baseline gap-x-2 font-mono text-xs">
            <span className="text-lg font-bold leading-none text-parchment-100">
              {formatEur(listing.price)}
            </span>
            {listing.shipping_price > 0 && (
              <span className="text-ink-600">+{formatEur(listing.shipping_price)} port</span>
            )}
            {listing.margin_net !== null && (
              <span
                className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ${
                  marginPositive ? "bg-moss-500/20 text-moss-400" : "bg-rust-500/15 text-rust-400"
                }`}
              >
                {marginPositive ? "+" : ""}
                {formatEur(listing.margin_net)}
              </span>
            )}
          </div>

          {hasNoPrice ? (
            <p className="mt-1.5 text-[11px] text-ink-600">
              Prix marché introuvable — l&apos;index se construit encore, ou carte non identifiée
            </p>
          ) : (
            <div className="mt-1.5 space-y-0.5">
              <div className="flex items-baseline gap-1.5 font-mono text-[11px]">
                <span className="text-ink-600">marché</span>
                <span className="font-semibold text-parchment-100">
                  {formatEur(listing.reference_price)}
                </span>
                {hasRange && (
                  <span
                    className="text-ink-600"
                    title="Fourchette dérivée de la volatilité sur 7 jours — ce n'est pas un historique de ventes conclues"
                  >
                    ({formatEur(listing.price_low_eur)}–{formatEur(listing.price_high_eur)})
                  </span>
                )}
              </div>
              {confidence && (
                <p
                  className={`text-[10px] ${
                    confidence === "high"
                      ? "text-moss-400"
                      : confidence === "medium"
                      ? "text-ember-400"
                      : "text-rust-400"
                  }`}
                  title={listing.price_detail?.reason ?? undefined}
                >
                  {CONFIDENCE_LABEL[confidence] ?? confidence}
                  {listing.price_detail?.matched_card
                    ? ` · ${listing.price_detail.matched_card}`
                    : ""}
                </p>
              )}

              {/* Combien de cartes homonymes ont dû être départagées, et sur
                  quelle amplitude de prix. Sans ça, un prix médian calculé
                  entre 3 € et 250 € s'affiche avec le même aplomb qu'un prix
                  sûr. */}
              {ambiguousCount > 1 && (
                <p className="text-[10px] text-ink-600">
                  {ambiguousCount} cartes portent ce nom
                  {spread > 0 && minPrice !== null &&
                    ` (de ${formatEur(minPrice)} à ${formatEur(maxPrice)})`}
                  {" "}— prix médian retenu
                </p>
              )}

              {priceWarning && (
                <p className="mt-1 rounded-sm border border-rust-500/40 bg-rust-500/10 px-1.5 py-1 text-[10px] leading-snug text-rust-400">
                  ⚠ {priceWarning}
                </p>
              )}
            </div>
          )}

          <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 text-[11px] text-ink-600">
            {listing.quality_vision_score !== null ? (
              <span title="Estimation depuis les photos — pas un grading professionnel">
                photo ~{Math.round(listing.quality_vision_score)}/100*
              </span>
            ) : listing.quality_text_score !== null ? (
              <span title="Estimation depuis le texte de l'annonce uniquement">
                texte ~{Math.round(listing.quality_text_score)}/100*
              </span>
            ) : null}
            {listing.seller_reliability_score !== null && (
              <span>vendeur {Math.round(listing.seller_reliability_score)}/100</span>
            )}
            <span>{timeAgo(listing.first_seen_at)}</span>
          </div>
        </div>

        <DealScoreBadge score={listing.deal_score} />
      </a>

      {hasNoPrice && (
        <a
          href={searchUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="block border-t border-ink-700 px-3 py-1.5 text-center text-[10px] text-ink-600 transition-colors hover:bg-ink-700 hover:text-ember-400"
        >
          Chercher le prix manuellement ↗
        </a>
      )}
    </article>
  );
}
