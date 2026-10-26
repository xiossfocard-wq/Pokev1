"use client";

import { useState } from "react";
import Image from "next/image";
import type { Listing } from "@/lib/api";
import { formatEur } from "@/lib/format";
import { useModeEvaluation } from "@/lib/mode";
import { dansLeBudget, useCartesSuivies } from "@/lib/suivi";
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

/**
 * Les raretés du jeu One Piece, sous le sigle qu'un joueur lit sur la carte.
 *
 * Elles arrivent sous deux formes : le code du catalogue (« SEC (Secret
 * Rare) ») et le libellé déduit du titre (« Secret Rare », « Alternative »).
 * Les styles étaient restés ceux du jeu Pokémon (« Special Illustration
 * Rare », « Hyper Rare »…) : aucune carte One Piece n'en recevait un.
 */
const RARETES: { motif: RegExp; sigle: string; nom: string; style: string }[] = [
  { motif: /^manga/i, sigle: "Manga", nom: "Manga Rare", style: "bg-gradient-to-r from-fuchsia-500/30 to-amber-400/30 text-amber-200 ring-1 ring-amber-400/50" },
  { motif: /^(sec\b|secret)/i, sigle: "SEC", nom: "Secret Rare", style: "bg-gradient-to-r from-fuchsia-500/25 to-amber-400/25 text-amber-200 ring-1 ring-amber-400/40" },
  { motif: /^(tr\b|treasure)/i, sigle: "TR", nom: "Treasure Rare", style: "bg-gradient-to-r from-amber-400/25 to-yellow-300/20 text-amber-200 ring-1 ring-amber-300/40" },
  { motif: /^(sp\b|sp card|special)/i, sigle: "SP", nom: "Carte spéciale", style: "bg-gradient-to-r from-sky-400/25 to-fuchsia-500/25 text-sky-200 ring-1 ring-sky-400/40" },
  { motif: /^alternative/i, sigle: "Alt", nom: "Illustration alternative", style: "bg-ember-500/20 text-ember-400 ring-1 ring-ember-500/40" },
  { motif: /^(sr\b|super rare)/i, sigle: "SR", nom: "Super Rare", style: "bg-violet-500/20 text-violet-300 ring-1 ring-violet-400/30" },
  { motif: /^(l\b|leader)/i, sigle: "L", nom: "Leader", style: "bg-rust-500/15 text-rust-400 ring-1 ring-rust-400/30" },
  { motif: /^(p\b|promo)/i, sigle: "P", nom: "Promo", style: "bg-moss-500/15 text-moss-400" },
  { motif: /^(r\b|rare)/i, sigle: "R", nom: "Rare", style: "bg-cyan-500/15 text-cyan-300" },
  { motif: /^(uc\b|uncommon)/i, sigle: "UC", nom: "Peu commune", style: "bg-ink-700 text-parchment-100" },
  { motif: /^(c\b|common)/i, sigle: "C", nom: "Commune", style: "bg-ink-700 text-ink-400" },
];

function rarete(libelle: string) {
  return RARETES.find((r) => r.motif.test(libelle.trim())) ?? {
    sigle: libelle, nom: libelle, style: "bg-ember-500/15 text-ember-400",
  };
}

const ETATS: Record<string, string> = {
  NM: "Near Mint : comme neuve",
  LP: "Light Played : légères traces",
  MP: "Moderately Played : usure visible",
  HP: "Heavily Played : très abîmée",
  DMG: "Damaged : endommagée",
};

/**
 * Ce qu'on cherche sur Cardmarket, et quelle fiche y choisir.
 *
 * Cardmarket nomme ses cartes One Piece « Shanks (OP01-120) (V.2) » : nom
 * anglais, CODE, puis version. Chercher le code trouve toutes les versions
 * et rééditions d'une carte (vérifié : « OP01-120 » renvoie ses 15 fiches,
 * Romance Dawn, The Best, japonaises, promos), là où le nom seul renvoie
 * tous les Shanks du jeu, et où un nom français peut ne rien trouver.
 *
 * La version se lit au rang de la fiche, comme rang_de_parallele côté
 * serveur : l'impression ordinaire est la V.1, la première illustration
 * alternative la V.2, la seconde (le manga) la V.3 — l'ordre vérifié sur
 * OP01-120, où les prix le confirment (3,99 €, 78,90 €, 2 130 €).
 */
function rechercheCardmarket(listing: Listing): { texte: string; version: string | null } {
  const d = listing.price_detail;
  const identifiee = d && d.confidence !== "manual";
  if (identifiee && d.matched_code) {
    const rang = d.matched_name_slug?.match(/-(?:parallele|alternative|alt)(?:-(\d+))?$/);
    const version = rang ? `V.${(rang[1] ? Number(rang[1]) : 1) + 1}` : "V.1";
    return { texte: d.matched_code, version };
  }
  const code = listing.title.match(/\b(?:OP|ST|EB|PRB)\d{2}-\d{3}\b/i);
  if (code) return { texte: code[0].toUpperCase(), version: null };
  // Ni code ni identification : le nom reconnu, sans la mention de version
  // (« Shanks (Parallèle 1) » ne trouve rien), sinon le titre de l'annonce.
  if (identifiee && d.matched_card) {
    const nom = d.matched_card.replace(/\s*\((?:parall[eè]le|manga|alternative|alt)[^)]*\)\s*$/i, "").trim();
    if (nom) return { texte: nom, version: null };
  }
  return { texte: listing.title, version: null };
}

/** Le détail du coût, lisible au survol : d'où vient chaque euro. */
function detailDuCout(listing: Listing): string | undefined {
  const c = listing.purchase_cost_detail;
  if (!c) return undefined;
  const lignes = [`Article ${formatEur(c.article)}`];
  if (c.protection > 0) {
    lignes.push(`Protection acheteur ${formatEur(c.protection)}${c.origine_protection?.startsWith("calcul") ? " (0,70 € + 5 %)" : ""}`);
  }
  if (c.port > 0) lignes.push(`Port ${formatEur(c.port)}${c.port_estime ? " (estimé : Vinted le fixe au panier)" : ""}`);
  return lignes.join(" · ");
}

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
    listing.title + " one piece carte prix"
  )}`;
  // Cardmarket exige l'extension exacte dans l'URL d'une fiche produit,
  // indevinable depuis un titre Vinted : on pointe vers leur recherche.
  const cardmarket = rechercheCardmarket(listing);
  const cardmarketUrl = `https://www.cardmarket.com/fr/OnePiece/Products/Search?searchString=${encodeURIComponent(
    cardmarket.texte
  )}`;
  const mode = useModeEvaluation();
  const economie = listing.savings_eur;
  const montrerEconomie = mode === "collection" && economie !== null && economie !== undefined;
  const cout = listing.purchase_cost_eur;
  const coutDiffere = cout !== null && cout !== undefined && Math.abs(cout - listing.price) >= 0.01;
  const nonComparable = detail?.non_comparable;
  const decote = detail?.etat_retenu;
  // « Ma liste » : la carte est-elle suivie, et l'annonce dans le budget ?
  const { budgets } = useCartesSuivies();
  const suivie = listing.matched_card_id != null && budgets.has(listing.matched_card_id);
  const budget = suivie ? budgets.get(listing.matched_card_id as number) : undefined;
  const coutReel = cout ?? listing.price + (listing.shipping_price ?? 0);
  const danslebudget = suivie && dansLeBudget(budget, coutReel, nonComparable);

  return (
    <article
      className={`group relative overflow-hidden rounded-lg border bg-ink-800/70 transition-colors hover:border-ember-500/40 hover:bg-ink-800 ${
        danslebudget ? "border-amber-300/60 ring-1 ring-amber-300/30" : "border-ink-700"
      }`}
    >
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
            <div className="flex h-full items-center justify-center px-1 text-center text-[9px] text-ink-400">
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
                className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${CONDITION_STYLES[listing.condition_tier] ?? "bg-ink-700 text-ink-400"}`}
                title={`${ETATS[listing.condition_tier] ?? listing.condition_tier} — le pire de l'état écrit dans l'annonce et de celui coché par le vendeur`}
              >
                {listing.condition_tier}
              </span>
            )}
            {listing.rarity_tier && (() => {
              const r = rarete(listing.rarity_tier);
              return (
                <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${r.style}`} title={r.nom}>
                  {r.sigle}
                </span>
              );
            })()}
            {suivie && (
              <span
                className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                  danslebudget ? "bg-amber-300/20 text-amber-200 ring-1 ring-amber-300/50" : "bg-amber-300/10 text-amber-200/80"
                }`}
                title={
                  budget == null
                    ? "Carte de ta liste (sans budget)"
                    : danslebudget
                    ? `Dans ton budget de ${formatEur(budget)} (coût réel, frais compris)`
                    : `Carte de ta liste — au-dessus de ton budget de ${formatEur(budget)}`
                }
              >
                {danslebudget ? "★ dans ton budget" : "★ Ma liste"}
              </span>
            )}
            {nonComparable && (
              <span
                className="rounded bg-sky-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-sky-300"
                title={nonComparable}
              >
                {nonComparable.startsWith("Carte gradée") ? "Gradée" : "Lot"}
              </span>
            )}
            {listing.is_vintage && (
              // « Vintage » pour une carte de 2022 faisait sourire un
              // collectionneur : ce sont les PREMIERS sets du jeu.
              <span
                className="rounded bg-moss-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-moss-400"
                title="Premiers sets du jeu (Romance Dawn, Paramount War) ou première édition : recherchés des collectionneurs"
              >
                1ers sets
              </span>
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
            {coutDiffere ? (
              <span className="text-ink-400" title={detailDuCout(listing)}>
                ≈ {formatEur(cout)} payé
              </span>
            ) : listing.shipping_price > 0 ? (
              <span className="text-ink-400">+{formatEur(listing.shipping_price)} port</span>
            ) : null}
            {montrerEconomie ? (
              <span
                className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ${
                  uncertain
                    ? "bg-ink-700 text-ink-400 line-through decoration-ink-600/60"
                    : economie >= 0
                    ? "bg-moss-500/20 text-moss-400"
                    : "bg-rust-500/15 text-rust-400"
                }`}
                title={
                  uncertain
                    ? "Économie calculée sur un prix incertain — elle ne compte pas dans le score."
                    : `${economie >= 0 ? "Ce que tu paies de moins" : "Ce que tu paies de plus"} que la cote${
                        decote ? " (ramenée à l'état de la carte)" : ""
                      }, protection acheteur et port compris${
                        listing.savings_ratio != null && economie >= 0
                          ? ` : ${Math.round(listing.savings_ratio * 100)} % sous la cote`
                          : ""
                      }. Sans compter le port d'un achat sur Cardmarket : l'écart réel est un peu plus favorable.${
                        listing.margin_net != null ? ` Si tu revendais : marge ${formatEur(listing.margin_net)}.` : ""
                      }`
                }
              >
                {economie >= 0 ? `économie ${formatEur(economie)}` : `${formatEur(-economie)} plus cher`}
              </span>
            ) : listing.margin_net !== null && (
              <span
                className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ${
                  uncertain
                    ? "bg-ink-700 text-ink-400 line-through decoration-ink-600/60"
                    : marginPositive
                    ? "bg-moss-500/20 text-moss-400"
                    : "bg-rust-500/15 text-rust-400"
                }`}
                title={
                  uncertain
                    ? "Marge calculée sur un prix incertain — elle ne compte pas dans le score."
                    : "Marge nette estimée : cote (ajustée à l'état) moins les frais de revente sur Cardmarket, moins ce que l'achat coûte vraiment."
                }
              >
                {marginPositive ? "+" : ""}
                {formatEur(listing.margin_net)}
              </span>
            )}
          </div>

          {hasNoPrice ? (
            <p className="mt-1.5 flex items-start gap-1.5 text-[11px] leading-snug text-ink-400">
              <span className="mt-1 inline-block h-2 w-2 shrink-0 rounded-full ring-1 ring-ink-400" />
              {nonComparable ?? "Prix marché introuvable"}
            </p>
          ) : (
            <p className="mt-1.5 flex flex-wrap items-center gap-x-1.5 text-[11px]">
              {meta && <span className={`inline-block h-2 w-2 rounded-full ${meta.dot}`} />}
              <span className="text-ink-400">cote</span>
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

          {decote && (
            <p className="mt-1 text-[11px] text-ink-400" title="La cote est celle d'une carte en très bon état">
              état {decote.etat} : cote ramenée à{" "}
              <span className="tabular font-mono text-parchment-100">{formatEur(decote.reference_ajustee)}</span>{" "}
              (×{decote.coefficient.toLocaleString("fr-FR")})
            </p>
          )}

          {detail?.alerte && (
            <p className="mt-1.5 rounded-md border border-ember-500/40 bg-ember-500/10 px-2 py-1 text-[10px] leading-snug text-ember-400">
              ⚠ {detail.alerte}
            </p>
          )}

          {detail?.warning && (
            <p className="mt-1.5 rounded-md border border-rust-500/40 bg-rust-500/10 px-2 py-1 text-[10px] leading-snug text-rust-400">
              ⚠ {detail.warning}
            </p>
          )}

          <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 text-[11px] text-ink-400">
            {listing.quality_vision_score !== null ? (
              <span title="Qualité estimée sur les photos de l'annonce — pas un grading professionnel">
                qualité (photos) ~{Math.round(listing.quality_vision_score)}/100
              </span>
            ) : listing.quality_text_score !== null ? (
              <span title="Qualité estimée sur le texte de l'annonce seulement : précision de la description, état annoncé">
                qualité (texte) ~{Math.round(listing.quality_text_score)}/100
              </span>
            ) : null}
            {listing.seller_reliability_score !== null && (
              <span title="Fiabilité du vendeur : nombre d'avis et note moyenne">
                fiabilité vendeur {Math.round(listing.seller_reliability_score)}/100
              </span>
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
        className="flex w-full items-center justify-center gap-1.5 border-t border-ink-700 py-1.5 text-[11px] text-ink-400 transition-colors hover:text-ember-400 md:hidden"
      >
        {panelOpen ? "Fermer" : "Détail & corriger"}
        <span aria-hidden="true">{panelOpen ? "⌃" : "⌄"}</span>
      </button>

      <div className={panelOpen ? "block" : "hidden md:group-focus-within:block md:group-hover:block"}>
        <CorrectionPanel
          listing={listing}
          cardmarketUrl={cardmarketUrl}
          cardmarketVersion={cardmarket.version}
          searchUrl={searchUrl}
          onChanged={onChanged}
        />
      </div>
    </article>
  );
}
