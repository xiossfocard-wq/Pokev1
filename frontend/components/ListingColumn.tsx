"use client";

import type { Listing, ListingSource, SortField, SortOrder } from "@/lib/api";
import ListingCard from "./ListingCard";
import ListingSkeleton from "./ListingSkeleton";
import SortBar from "./SortBar";

interface ListingColumnProps {
  source: ListingSource;
  listings: Listing[];
  /** Nombre avant filtrage côté navigateur, pour dire « 12 sur 100 ». */
  total: number;
  loading: boolean;
  sortBy: SortField;
  order: SortOrder;
  onSortChange: (sortBy: SortField, order: SortOrder) => void;
  onListingChanged?: (updated: Listing) => void;
}

const SOURCE_LABEL: Record<ListingSource, string> = { vinted: "Vinted", ebay: "eBay" };
const SOURCE_DOT: Record<ListingSource, string> = { vinted: "bg-moss-400", ebay: "bg-ember-400" };

export default function ListingColumn({
  source,
  listings,
  total,
  loading,
  sortBy,
  order,
  onSortChange,
  onListingChanged,
}: ListingColumnProps) {
  const filtered = listings.length !== total;

  return (
    <section className="min-w-0 flex-1" aria-label={SOURCE_LABEL[source]}>
      <div className="sticky top-[3.6rem] z-10 -mx-1 mb-2 flex items-center justify-between rounded-md bg-ink-950/85 px-1 py-1.5 backdrop-blur">
        <h2 className="flex items-center gap-2 font-display text-lg text-parchment-100">
          <span className={`h-2 w-2 rounded-full ${SOURCE_DOT[source]}`} />
          {SOURCE_LABEL[source]}
          <span className="tabular font-mono text-xs font-normal text-ink-600">
            {filtered ? `${listings.length} / ${total}` : total}
          </span>
        </h2>
        <SortBar sortBy={sortBy} order={order} onChange={onSortChange} />
      </div>

      <div className="flex flex-col gap-2">
        {loading && (
          <>
            <ListingSkeleton />
            <ListingSkeleton />
            <ListingSkeleton />
          </>
        )}

        {!loading && listings.length === 0 && (
          <div className="rounded-lg border border-dashed border-ink-700 px-4 py-8 text-center">
            <p className="text-sm text-parchment-100">
              {filtered ? "Rien ne passe ces filtres." : "Aucune annonce pour l'instant."}
            </p>
            <p className="mt-1 text-xs text-ink-600">
              {filtered
                ? "Élargis la fiabilité ou baisse le score minimum."
                : "Le prochain cycle de collecte en trouvera peut-être."}
            </p>
          </div>
        )}

        {!loading &&
          listings.map((l) => <ListingCard key={l.id} listing={l} onChanged={onListingChanged} />)}
      </div>
    </section>
  );
}
