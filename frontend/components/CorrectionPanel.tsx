"use client";

import { useState } from "react";
import { correctListing, type CorrectionAction, type Listing } from "@/lib/api";

interface CorrectionPanelProps {
  listing: Listing;
  cardmarketUrl: string;
  searchUrl: string;
  onChanged?: (updated: Listing) => void;
}

function formatEur(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("fr-FR", { style: "currency", currency: "EUR" });
}

const BTN = "rounded-md border px-2.5 py-1.5 text-[11px] font-medium transition-colors disabled:opacity-40";
const BTN_QUIET = `${BTN} border-ink-700 text-ink-600 hover:border-ink-600 hover:text-parchment-100`;
const BTN_NEUTRAL = `${BTN} border-ink-700 text-parchment-100 hover:border-ember-500 hover:text-ember-400`;
const BTN_DANGER = `${BTN} border-ink-700 text-parchment-100 hover:border-rust-500 hover:text-rust-400`;
const BTN_PRIMARY = `${BTN} border-ember-500/50 bg-ember-500/10 text-ember-400 hover:bg-ember-500/20`;

/**
 * Détail du marché + actions de correction, révélés au survol d'une carte.
 *
 * Toujours rendu EN DEHORS du lien principal de la carte : on ne peut pas
 * imbriquer des liens ou des boutons dans un lien.
 */
export default function CorrectionPanel({ listing, cardmarketUrl, searchUrl, onChanged }: CorrectionPanelProps) {
  const [busy, setBusy] = useState(false);
  const [editingPrice, setEditingPrice] = useState(false);
  const [priceInput, setPriceInput] = useState("");
  const [error, setError] = useState<string | null>(null);

  const detail = listing.price_detail;
  const reviewed = listing.manual_reviewed_at !== null;
  const hasRange = listing.price_low_eur != null && listing.price_high_eur != null;
  const homonyms = detail?.candidates_count ?? 0;

  async function apply(action: CorrectionAction, price?: number) {
    setBusy(true);
    setError(null);
    try {
      const updated = await correctListing(listing.id, action, price);
      setEditingPrice(false);
      setPriceInput("");
      onChanged?.(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function submitPrice() {
    const value = Number(priceInput.replace(",", "."));
    if (!Number.isFinite(value) || value <= 0) {
      setError("Entre un prix supérieur à 0, par exemple 42,50");
      return;
    }
    apply("set_price", value);
  }

  return (
    <div className="border-t border-ink-700 bg-ink-900/60 px-3 py-3">
      {detail ? (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px]">
          <dt className="text-ink-600">Carte retenue</dt>
          <dd className="text-parchment-100">
            {detail.matched_card}
            {detail.matched_code && (
              <span className="ml-1.5 font-mono text-ink-600">{detail.matched_code}</span>
            )}
          </dd>

          {detail.series_name && (
            <>
              <dt className="text-ink-600">Série</dt>
              <dd className="text-parchment-100">{detail.series_name}</dd>
            </>
          )}

          <dt className="text-ink-600">Prix marché</dt>
          <dd className="tabular font-mono text-parchment-100">
            {formatEur(detail.price_eur)}
            {hasRange && (
              <span className="ml-1.5 text-ink-600">
                volatilité 7 j : {formatEur(listing.price_low_eur)}–{formatEur(listing.price_high_eur)}
              </span>
            )}
          </dd>

          {homonyms > 1 && (
            <>
              <dt className="text-ink-600">Homonymes</dt>
              <dd className="text-parchment-100">
                {homonyms} cartes de ce nom
                {detail.candidates_min_eur != null && (
                  <span className="tabular font-mono text-ink-600">
                    {" "}({formatEur(detail.candidates_min_eur)} → {formatEur(detail.candidates_max_eur)})
                  </span>
                )}
              </dd>
            </>
          )}

          <dt className="text-ink-600">Pourquoi</dt>
          <dd className="text-ink-600">{detail.reason}</dd>
        </dl>
      ) : (
        <p className="text-[11px] text-ink-600">
          Aucune carte de l&apos;index ne correspond à ce titre — titre trop vague, ou carte
          absente de l&apos;index.
        </p>
      )}

      <div className="mt-2.5 flex flex-wrap gap-2 border-t border-ink-800 pt-2.5">
        <a href={cardmarketUrl} target="_blank" rel="noopener noreferrer" className={BTN_NEUTRAL}>
          Vérifier sur Cardmarket ↗
        </a>
        <a href={searchUrl} target="_blank" rel="noopener noreferrer" className={BTN_QUIET}>
          Recherche Google ↗
        </a>
      </div>

      <div className="mt-2.5 border-t border-ink-800 pt-2.5">
        {reviewed ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] text-ember-400">
              {listing.manual_status === "wrong_card"
                ? "Tu as signalé que la carte ne correspond pas."
                : listing.manual_status === "hidden"
                ? "Tu as masqué cette annonce."
                : `Prix corrigé par toi : ${formatEur(listing.manual_reference_price)}.`}
            </span>
            <button type="button" disabled={busy} onClick={() => apply("reset")} className={BTN_QUIET}>
              Annuler ma correction
            </button>
          </div>
        ) : editingPrice ? (
          <div className="flex flex-wrap items-center gap-2">
            <label className="text-[11px] text-ink-600" htmlFor={`prix-${listing.id}`}>
              Prix réel du marché
            </label>
            <input
              id={`prix-${listing.id}`}
              type="text"
              inputMode="decimal"
              autoFocus
              value={priceInput}
              onChange={(e) => setPriceInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") submitPrice();
                if (e.key === "Escape") setEditingPrice(false);
              }}
              placeholder="42,50"
              className="tabular w-24 rounded-md border border-ink-700 bg-ink-800 px-2 py-1.5 font-mono text-[11px] text-parchment-100 placeholder:text-ink-600 focus:border-ember-500 focus:outline-none"
            />
            <button type="button" disabled={busy} onClick={submitPrice} className={BTN_PRIMARY}>
              Valider
            </button>
            <button
              type="button"
              onClick={() => setEditingPrice(false)}
              className="text-[11px] text-ink-600 underline hover:text-parchment-100"
            >
              Annuler
            </button>
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={busy} onClick={() => apply("wrong_card")} className={BTN_DANGER}>
              Ce n&apos;est pas la bonne carte
            </button>
            <button type="button" disabled={busy} onClick={() => setEditingPrice(true)} className={BTN_NEUTRAL}>
              Corriger le prix
            </button>
            <button type="button" disabled={busy} onClick={() => apply("hide")} className={BTN_QUIET}>
              Masquer
            </button>
          </div>
        )}

        {error && <p className="mt-1.5 text-[11px] text-rust-400">{error}</p>}
      </div>
    </div>
  );
}
