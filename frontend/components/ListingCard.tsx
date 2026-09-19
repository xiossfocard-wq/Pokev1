"use client";

import { useState } from "react";
import Image from "next/image";
import type { Listing } from "@/lib/api";
import DealScoreBadge from "./DealScoreBadge";
import CorrectionPanel from "./CorrectionPanel";

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

/**
 * Langage visuel de la fiabilité, lisible d'un coup d'œil sur toute la
 * liste : un point plein = prix sûr, demi = probable, creux = incertain.
 * La couleur seule ne suffit pas (daltonisme) : la forme porte aussi
 * l'information.
 */
const CONFIDENCE: Record<string, { label: string; dot: string; text: string }> = {
  manual: { label: "Prix corrigé par toi", dot: "bg-ember-400 ring-2 ring-ember-400/30", text: "text-ember-400" },
  high: { label: "Prix fiable", dot: "bg-moss-400", text: "text-moss-400" },
  medium: { label: "Prix probable", dot: "bg-ember-400/60 ring-1 ring-ember-400", text: "text-ember-400" },
  low: { label: "Prix incertain", dot: "bg-transparent ring-1 ring-rust-400", text: "text-rust-400" },
};

export default function ListingCard({
  listing,
  onChanged,
}: {
  listing: Listing;
  onChanged?: (updated: Listing) => void;
}) {
  // Sur mobile il n'y a pas de survol : un bouton toujours visible ouvre le
  // panneau. Sur ordinateur, le survol suffit et le bouton reste discret.
  const [panelOpen, setPanelOpen] = useState(false);
  const photo = listing.photo_urls?.[0];
  const detail = listing.price_detail;
  const confidence = listing.price_match_confidence;
  const meta = confidence ? CONFIDENCE[confidence] : null;
  const uncertain = detail?.uncertain === true;
  const marginPositive = (listing.margin_net ?? 0) > 0;
  const reviewed = listing.manual_reviewed_at !== null;
  const hasNoPrice = listing.reference_price === null;
  // L'URL vient de donnees collectees sur des sites tiers : on ne rend un
  // lien que si le schema est http(s), jamais javascript: ni data:.
  const safeUrl = /^https?:\/\//i.test(listing.url) ? listing.url : undefined;

  const searchUrl = `https://www.google.com/search?q=${encodeURIComponent(
    listing.title + " pokemon carte prix"
  )}`;
  // Cardmarket exige l'extension exacte dans l'URL d'une fiche produit,
  // indevinable depuis un titre Vinted : on pointe vers leur recherche.
  const cardmarketUrl = `https://www.cardmarket.com/fr/Pokemon/Products/Search?searchString=${encodeURIComponent(
    detail?.matched_card || listing.title
  )}`;

  return (
    <article className="group relative overflow-hidden rounded-lg border border-ink-700 bg-ink-800/70 transition-colors hover:border-ember-500/40 hover:bg-ink-800">
      <a
        href={safeUrl}
        target="_blank"
        rel="noopener noreferrer"
        aria-disabled={safeUrl ? undefined : true}
        className="flex gap-3 p-3"
      >
        <div className="relative h-24 w-[68px] shrink-0 overflow-hidden rounded-md bg-ink-700 ring-1 ring-ink-600">
          {photo ? (
            <Image src={photo} alt={`Photo de l'annonce : ${listing.title}`} fill sizes="68px" className="object-cover" unoptimized />
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
                className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${CONDITION_STYLES[listing.condition_tier] ?? "bg-ink-700 text-ink-600"}`}
                title="État déduit du texte de l'annonce"
              >
                {listing.condition_tier}
              </span>
            )}
            {listing.rarity_tier && (
              <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${RARITY_STYLES[listing.rarity_tier] ?? "bg-ember-500/15 text-ember-400"}`}>
                {listing.rarity_tier}
              </span>
            )}
            {listing.is_vintage && (
              <span className="rounded bg-moss-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-moss-400">Vintage</span>
            )}
            {reviewed && (
              <span
                className="rounded bg-ember-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-ember-400"
                title="Tu as corrigé cette annonce à la main — l'automatique ne revient plus dessus."
              >
                Corrigé par toi
              </span>
            )}
          </div>

          <div className="tabular mt-2 flex flex-wrap items-baseline gap-x-2 font-mono text-xs">
            <span className="text-lg font-bold leading-none text-parchment-100">
              {formatEur(listing.price)}
            </span>
            {listing.shipping_price > 0 && (
              <span className="text-ink-600">+{formatEur(listing.shipping_price)} port</span>
            )}
            {listing.margin_net !== null && (
              <span
                className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ${
                  uncertain
                    ? "bg-ink-700 text-ink-600 line-through decoration-ink-600/60"
                    : marginPositive
                    ? "bg-moss-500/20 text-moss-400"
                    : "bg-rust-500/15 text-rust-400"
                }`}
                title={uncertain ? "Marge calculée sur un prix incertain — elle ne compte pas dans le score." : undefined}
              >
                {marginPositive ? "+" : ""}
                {formatEur(listing.margin_net)}
              </span>
            )}
          </div>

          {hasNoPrice ? (
            <p className="mt-1.5 flex items-center gap-1.5 text-[11px] text-ink-600">
              <span className="inline-block h-2 w-2 rounded-full ring-1 ring-ink-600" />
              Prix marché introuvable
            </p>
          ) : (
            <p className="mt-1.5 flex flex-wrap items-center gap-x-1.5 text-[11px]">
              {meta && <span className={`inline-block h-2 w-2 rounded-full ${meta.dot}`} />}
              <span className="text-ink-600">marché</span>
              <span className="tabular font-mono font-semibold text-parchment-100">
                {formatEur(listing.reference_price)}
              </span>
              {meta && (
                <span className={meta.text} title={detail?.reason ?? undefined}>
                  · {meta.label}
                  {detail?.matched_card && confidence !== "manual" ? ` · ${detail.matched_card}` : ""}
                </span>
              )}
            </p>
          )}

          {detail?.warning && (
            <p className="mt-1.5 rounded-md border border-rust-500/40 bg-rust-500/10 px-2 py-1 text-[10px] leading-snug text-rust-400">
              ⚠ {detail.warning}
            </p>
          )}

          <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 text-[11px] text-ink-600">
            {listing.quality_vision_score !== null ? (
              <span title="Estimation depuis les photos — pas un grading professionnel">
                photo ~{Math.round(listing.quality_vision_score)}/100
              </span>
            ) : listing.quality_text_score !== null ? (
              <span title="Estimation depuis le texte de l'annonce uniquement">
                texte ~{Math.round(listing.quality_text_score)}/100
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

      {/* Sur mobile, pas de survol : une barre ouvre le panneau. Sur
          ordinateur elle est masquée et le survol fait le travail. */}
      <button
        type="button"
        onClick={() => setPanelOpen((o) => !o)}
        aria-expanded={panelOpen}
        className="flex w-full items-center justify-center gap-1.5 border-t border-ink-700 py-1.5 text-[11px] text-ink-600 transition-colors hover:text-ember-400 md:hidden"
      >
        {panelOpen ? "Fermer" : "Détail & corriger"}
        <span aria-hidden="true">{panelOpen ? "⌃" : "⌄"}</span>
      </button>

      <div className={panelOpen ? "block" : "hidden md:group-focus-within:block md:group-hover:block"}>
        <CorrectionPanel
          listing={listing}
          cardmarketUrl={cardmarketUrl}
          searchUrl={searchUrl}
          onChanged={onChanged}
        />
      </div>
    </article>
  );
}
