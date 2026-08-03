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

function formatEur(value: number | null): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("fr-FR", { style: "currency", currency: "EUR" });
}

export default function ListingCard({ listing }: { listing: Listing }) {
  const photo = listing.photo_urls?.[0];
  const marginPositive = (listing.margin_net ?? 0) > 0;

  return (
    <a
      href={listing.url}
      target="_blank"
      rel="noopener noreferrer"
      className="group flex gap-3 rounded-md border border-ink-700 bg-ink-800 p-3 transition-colors hover:border-ember-500/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ember-500"
    >
      <div className="relative h-20 w-20 shrink-0 overflow-hidden rounded-sm bg-ink-700">
        {photo ? (
          <Image src={photo} alt="" fill sizes="80px" className="object-cover" unoptimized />
        ) : (
          <div className="flex h-full items-center justify-center text-[10px] text-ink-600">
            pas de photo
          </div>
        )}
      </div>

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-parchment-100 group-hover:text-ember-400">
          {listing.title}
        </p>

        <div className="mt-1 flex flex-wrap items-baseline gap-x-2 font-mono text-xs">
          <span className="text-base font-semibold text-parchment-100">
            {formatEur(listing.price)}
          </span>
          {listing.shipping_price > 0 && (
            <span className="text-ink-600">+ {formatEur(listing.shipping_price)} port</span>
          )}
          {listing.reference_price && (
            <span className="text-ink-600">
              · réf. {formatEur(listing.reference_price)}
              {listing.reference_price_source ? ` (${listing.reference_price_source})` : ""}
            </span>
          )}
        </div>

        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          {listing.margin_net !== null && (
            <span className={marginPositive ? "text-moss-400" : "text-rust-400"}>
              {marginPositive ? "+" : ""}
              {formatEur(listing.margin_net)} marge
            </span>
          )}
          {listing.quality_vision_score !== null && (
            <span
              className="text-ink-600"
              title="Estimation indicative à partir des photos — pas un grading professionnel (PSA/BGS/CGC)"
            >
              qualité photo ~{Math.round(listing.quality_vision_score)}/100*
            </span>
          )}
          {listing.seller_reliability_score !== null && (
            <span className="text-ink-600">
              vendeur {Math.round(listing.seller_reliability_score!)}/100
            </span>
          )}
          <span className="text-ink-600">{timeAgo(listing.first_seen_at)}</span>
        </div>
      </div>

      <DealScoreBadge score={listing.deal_score} />
    </a>
  );
}
