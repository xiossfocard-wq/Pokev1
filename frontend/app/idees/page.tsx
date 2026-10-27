"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import CardDetailPanel from "@/components/CardDetailPanel";
import Raisons from "@/components/Raisons";
import VisuelCarte from "@/components/VisuelCarte";
import {
  ecarterIdee,
  enregistrerGouts,
  fetchGouts,
  fetchIdees,
  revoirIdeesEcartees,
  type CarteIdee,
  type Gouts,
  type IdeeDeCollection,
  type Idees,
  type OptionsGouts,
  type ProjetCollection,
} from "@/lib/api";
import { formatEur } from "@/lib/format";
import { suivre, useCartesSuivies } from "@/lib/suivi";

/**
 * Idées de collection : ce qu'un connaisseur conseillerait, pas seulement
 * les bonnes affaires. De belles cartes (illustrations alternatives, SP…) de
 * personnages qui comptent, encore accessibles ; celles qui montent ; celles
 * qui coûtent moins que leurs semblables ; et des projets de collection à
 * thème. Chaque suggestion dit pourquoi.
 */

const BUDGETS = [5, 10, 20, 50, 100];
const CLE_BUDGET = "idees-budget";

function lireBudget(): number {
  try {
    const v = Number(window.localStorage.getItem(CLE_BUDGET));
    return BUDGETS.includes(v) ? v : 20;
  } catch {
    return 20;
  }
}

export default function IdeesPage() {
  const [budget, setBudget] = useState(20);
  const [toutesLangues, setToutesLangues] = useState(false);
  const [idees, setIdees] = useState<Idees | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [carteOuverte, setCarteOuverte] = useState<number | null>(null);
  const [ecartees, setEcartees] = useState<Set<number>>(new Set());

  useEffect(() => setBudget(lireBudget()), []);

  const charger = useCallback(() => {
    setIdees(null);
    setErreur(null);
    fetchIdees(budget, toutesLangues)
      .then(setIdees)
      .catch((e) => setErreur(e instanceof Error ? e.message : String(e)));
  }, [budget, toutesLangues]);
  useEffect(charger, [charger]);

  function choisirBudget(b: number) {
    setBudget(b);
    try {
      window.localStorage.setItem(CLE_BUDGET, String(b));
    } catch {
      /* préférence non mémorisée : sans conséquence */
    }
  }

  async function ecarter(id: number) {
    setEcartees((s) => new Set(s).add(id));
    try {
      await ecarterIdee(id);
    } catch {
      setEcartees((s) => {
        const copie = new Set(s);
        copie.delete(id);
        return copie;
      });
    }
  }

  const rien = idees && idees.rubriques.length === 0 && idees.themes.length === 0;

  return (
    <>
      <header className="sticky top-0 z-20 border-b border-ink-800 bg-ink-950/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-2.5">
          <Link href="/" className="font-display text-lg leading-none text-parchment-100">
            Radar
          </Link>
          <span className="text-ink-400">/</span>
          <span className="text-sm text-parchment-100">Idées</span>
          <div className="ml-auto flex gap-1.5">
            <Link
              href="/suivi"
              className="rounded-md border border-ink-700 px-2.5 py-1.5 text-xs text-parchment-100 transition-colors hover:border-ember-500"
            >
              ★ Ma liste
            </Link>
            <Link
              href="/collection"
              className="rounded-md border border-ink-700 px-2.5 py-1.5 text-xs text-parchment-100 transition-colors hover:border-ember-500"
            >
              Collection
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 pb-16 pt-6">
        <h1 className="font-display text-2xl text-parchment-100">Idées de collection</h1>
        <p className="mt-1 max-w-3xl text-xs leading-relaxed text-ink-400">
          De belles cartes — illustrations alternatives, SP, Leaders parallèles — de personnages qui comptent,
          encore accessibles ; celles dont la cote monte ; celles qui coûtent moins que leurs semblables. Chaque
          suggestion dit pourquoi. Ce sont des repères pour se faire plaisir, pas des conseils de placement.
        </p>

        <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2">
          <div className="flex items-center gap-1.5" role="group" aria-label="Budget par carte">
            <span className="mr-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-400">Budget</span>
            {BUDGETS.map((b) => (
              <button
                key={b}
                type="button"
                aria-pressed={b === budget}
                onClick={() => choisirBudget(b)}
                className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
                  b === budget
                    ? "border-ember-500/60 bg-ember-500/15 text-ember-400"
                    : "border-ink-700 text-ink-400 hover:border-ink-600 hover:text-parchment-100"
                }`}
              >
                ≤ {b} €
              </button>
            ))}
          </div>
          <label className="flex items-center gap-2 text-xs text-ink-400">
            <input
              type="checkbox"
              checked={toutesLangues}
              onChange={(e) => setToutesLangues(e.target.checked)}
              className="accent-ember-500"
            />
            Inclure les séries sans version française
          </label>
        </div>

        <MesGouts onEnregistre={charger} />

        {erreur && (
          <div className="mt-4 rounded-md border border-rust-500/40 bg-rust-500/10 px-3 py-2 text-xs text-rust-400">
            Impossible de charger les idées. [{erreur}]
          </div>
        )}

        {idees && idees.projets.length > 0 && (
          <section className="mt-8" aria-labelledby="tes-projets">
            <h2 id="tes-projets" className="font-display text-xl text-parchment-100">
              Tes projets
            </h2>
            <p className="mt-0.5 text-xs text-ink-400">
              Les belles versions de tes préférés — illustrations alternatives, SP, Manga, Leaders parallèles : où tu
              en es, et par quoi continuer.
            </p>
            <ul className="mt-3 grid list-none gap-3 p-0 sm:grid-cols-2 lg:grid-cols-3">
              {idees.projets.map((projet) => (
                <Projet key={`${projet.nature}-${projet.nom}`} projet={projet} budget={budget} onOuvrir={setCarteOuverte} />
              ))}
            </ul>
          </section>
        )}

        {!idees && !erreur && (
          <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="skeleton aspect-[63/120]" />
            ))}
          </div>
        )}

        {rien && (
          <div className="mt-6 rounded-lg border border-dashed border-ink-700 px-4 py-10 text-center">
            <p className="text-sm text-parchment-100">Aucune idée dans ce budget pour l&apos;instant.</p>
            <p className="mt-1 text-xs text-ink-400">
              Essaie un budget plus large. Les idées s&apos;appuient sur les cotes du catalogue : elles
              s&apos;enrichissent à mesure que les prix sont relevés.
            </p>
          </div>
        )}

        {idees?.rubriques.map((rubrique) => {
          const cartes = rubrique.cartes.filter((c) => !ecartees.has(c.id));
          if (cartes.length === 0) return null;
          return (
            <section key={rubrique.cle} className="mt-8" aria-labelledby={`rubrique-${rubrique.cle}`}>
              <h2 id={`rubrique-${rubrique.cle}`} className="font-display text-xl text-parchment-100">
                {rubrique.titre}
              </h2>
              <p className="mt-0.5 text-xs text-ink-400">{rubrique.explication}</p>
              <ul className="mt-3 grid list-none grid-cols-2 gap-3 p-0 sm:grid-cols-3 lg:grid-cols-4">
                {cartes.map((carte) => (
                  <TuileIdee key={carte.id} carte={carte} onOuvrir={setCarteOuverte} onEcarter={ecarter} />
                ))}
              </ul>
            </section>
          );
        })}

        {idees && idees.themes.length > 0 && (
          <section className="mt-10" aria-labelledby="projets">
            <h2 id="projets" className="font-display text-xl text-parchment-100">
              Projets de collection à thème
            </h2>
            <p className="mt-0.5 text-xs text-ink-400">
              Les illustrations alternatives d&apos;un équipage ou d&apos;un groupe, chacune à moins de{" "}
              {formatEur(budget, 0)}, et ce que coûterait l&apos;ensemble.
            </p>
            <ul className="mt-3 grid list-none gap-3 p-0 sm:grid-cols-2 lg:grid-cols-3">
              {idees.themes.map((idee) => (
                <ProjetTheme key={idee.slug} idee={idee} budget={budget} />
              ))}
            </ul>
          </section>
        )}

        {idees && (
          <p className="mt-10 border-t border-ink-800 pt-4 text-center text-[11px] leading-relaxed text-ink-400">
            {idees.cartes_examinees} cartes examinées dans ce budget. Suggestions automatiques, fondées sur la cote,
            la tendance mesurée, la version de la carte et la notoriété du personnage — ton œil a le dernier mot.{" "}
            <button
              type="button"
              onClick={async () => {
                await revoirIdeesEcartees();
                setEcartees(new Set());
                charger();
              }}
              className="underline decoration-ink-600 underline-offset-2 hover:text-parchment-100"
            >
              Revoir les cartes écartées
            </button>
          </p>
        )}
      </main>

      {carteOuverte !== null && (
        <CardDetailPanel cardId={carteOuverte} onClose={() => setCarteOuverte(null)} />
      )}
    </>
  );
}

function TuileIdee({
  carte,
  onOuvrir,
  onEcarter,
}: {
  carte: CarteIdee;
  onOuvrir: (id: number) => void;
  onEcarter: (id: number) => void;
}) {
  const { budgets } = useCartesSuivies();
  const suivie = carte.suivie || budgets.has(carte.id);
  const [occupe, setOccupe] = useState(false);

  async function suivreLaCarte() {
    setOccupe(true);
    try {
      // Le budget part de la cote : c'est le prix auquel la carte s'achète
      // ailleurs. Il se règle ensuite dans « Ma liste ».
      await suivre(carte.id, carte.price_eur !== null ? Math.ceil(carte.price_eur) : null);
    } finally {
      setOccupe(false);
    }
  }

  return (
    <li className="flex flex-col overflow-hidden rounded-md border border-ink-700 bg-ink-900">
      <button
        type="button"
        onClick={() => onOuvrir(carte.id)}
        className="relative aspect-[63/88] w-full bg-ink-950"
        aria-label={`Ouvrir la fiche de ${carte.display_name}`}
      >
        <VisuelCarte
          src={carte.image_url}
          alt={carte.display_name}
          sizes="(max-width: 640px) 45vw, (max-width: 1024px) 30vw, 240px"
          repli={() => (
            <span className="flex h-full items-center justify-center p-2 text-center text-[10px] text-ink-400">
              Visuel pas encore récupéré
            </span>
          )}
        />
      </button>
      <div className="flex flex-1 flex-col gap-1.5 p-2.5">
        <div className="flex items-baseline justify-between gap-2">
          {/* Sans « (Parallèle 1) » : le badge du visuel le dit déjà. */}
          <p className="font-display text-sm leading-tight text-parchment-100">
            {carte.display_name.replace(/\s*\((?:parall[eè]le|manga)[^)]*\)\s*$/i, "")}
          </p>
          <p className="tabular shrink-0 font-mono text-sm text-parchment-100">
            {carte.price_eur !== null ? formatEur(carte.price_eur) : "—"}
          </p>
        </div>
        <p className="text-[10px] text-ink-400">
          {carte.card_code}
          {carte.series_name ? ` · ${carte.series_name}` : ""}
        </p>
        <Raisons raisons={carte.raisons} sans={["vinted"]} />
        <p className="text-[11px] italic leading-snug text-parchment-100/80">« {carte.avis} »</p>
        <div className="mt-auto flex items-center gap-1.5 pt-1">
          <button
            type="button"
            onClick={suivreLaCarte}
            disabled={suivie || occupe}
            className={`rounded-md border px-2 py-1 text-[11px] font-medium transition-colors ${
              suivie
                ? "border-amber-300/40 text-amber-200"
                : "border-amber-300/50 bg-amber-300/10 text-amber-200 hover:bg-amber-300/20"
            }`}
            title={suivie ? "Déjà dans ta liste" : "L'ajouter à Ma liste, avec la cote comme budget : tu seras prévenu dès qu'une annonce passe dessous"}
          >
            {suivie ? "★ Suivie" : occupe ? "…" : "☆ Suivre"}
          </button>
          {carte.listings_count > 0 && (
            <button
              type="button"
              onClick={() => onOuvrir(carte.id)}
              className="rounded-md border border-ink-700 px-2 py-1 text-[11px] text-parchment-100 hover:border-ember-500"
              title="Voir les annonces en vente"
            >
              {carte.listings_count} en vente
            </button>
          )}
          <button
            type="button"
            onClick={() => onEcarter(carte.id)}
            className="ml-auto text-[11px] text-ink-400 underline decoration-ink-600 underline-offset-2 hover:text-parchment-100"
            title="Ne plus me proposer cette carte"
          >
            pas pour moi
          </button>
        </div>
      </div>
    </li>
  );
}

function ProjetTheme({ idee, budget }: { idee: IdeeDeCollection; budget: number }) {
  return (
    <li className="rounded-lg border border-ink-700 bg-ink-800/60 p-3">
      <div className="flex gap-1.5">
        {idee.apercu.map((c) => (
          <div key={c.id} className="relative aspect-[63/88] w-1/4 overflow-hidden rounded-sm bg-ink-950">
            <VisuelCarte src={c.image_url} alt={c.display_name} sizes="80px" repli={() => null} />
          </div>
        ))}
      </div>
      <p className="mt-2 font-display text-base text-parchment-100">{idee.label}</p>
      <p className="text-xs text-ink-400">
        {idee.nombre} illustration{idee.nombre > 1 ? "s" : ""} alternative{idee.nombre > 1 ? "s" : ""} ·{" "}
        <span className="tabular font-mono text-parchment-100">{formatEur(idee.total_eur)}</span> l&apos;ensemble
        {idee.deja > 0 && <span className="text-moss-400"> · tu en as déjà {idee.deja}</span>}
      </p>
      <Link
        href={`/explorer?theme=${encodeURIComponent(idee.slug)}&prix_max=${budget}`}
        className="mt-2 inline-block text-xs text-ember-400 underline decoration-ember-500/40 underline-offset-2"
      >
        Voir les cartes
      </Link>
    </li>
  );
}

/**
 * Mes goûts : personnages, groupes et styles préférés. Les idées s'y
 * adaptent (« Selon tes goûts » en tête), et chaque préféré devient un projet
 * de collection suivi.
 */
function MesGouts({ onEnregistre }: { onEnregistre: () => void }) {
  const [ouvert, setOuvert] = useState(false);
  const [options, setOptions] = useState<OptionsGouts | null>(null);
  const [gouts, setGouts] = useState<Gouts>({ personnages: [], themes: [], styles: [] });
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  useEffect(() => {
    fetchGouts()
      .then((r) => {
        setOptions(r.options);
        setGouts(r.gouts);
      })
      .catch((e) => setErreur(e instanceof Error ? e.message : String(e)));
  }, []);

  function basculer(cle: keyof Gouts, valeur: string) {
    setGouts((g) => ({
      ...g,
      [cle]: g[cle].includes(valeur) ? g[cle].filter((v) => v !== valeur) : [...g[cle], valeur],
    }));
  }

  async function enregistrer() {
    setOccupe(true);
    setErreur(null);
    try {
      setGouts(await enregistrerGouts(gouts));
      setOuvert(false);
      onEnregistre();
    } catch (e) {
      setErreur(e instanceof Error ? e.message : String(e));
    } finally {
      setOccupe(false);
    }
  }

  const resume = [...gouts.personnages, ...gouts.themes.map((t) => options?.themes.find((o) => o.slug === t)?.label ?? t)];
  const puce = (actif: boolean) =>
    `rounded-full border px-2.5 py-1 text-xs transition-colors ${
      actif
        ? "border-amber-300/70 bg-amber-300/15 text-amber-100"
        : "border-ink-700 text-ink-400 hover:border-ink-600 hover:text-parchment-100"
    }`;

  return (
    <div className="mt-4 rounded-lg border border-amber-300/30 bg-amber-300/5 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="flex-1 text-xs text-parchment-100/80">
          <span className="font-medium text-amber-200">Mes goûts</span>
          {" · "}
          {resume.length > 0
            ? resume.join(", ")
            : "dis-moi qui tu aimes : les idées s'y adapteront, et chaque préféré deviendra un projet de collection."}
        </p>
        <button
          type="button"
          onClick={() => setOuvert((o) => !o)}
          aria-expanded={ouvert}
          className="rounded-md border border-amber-300/50 px-2.5 py-1 text-xs font-medium text-amber-200 hover:bg-amber-300/10"
        >
          {ouvert ? "Fermer" : resume.length > 0 ? "Modifier" : "Choisir"}
        </button>
      </div>

      {ouvert && options && (
        <div className="mt-3 flex flex-col gap-3">
          <fieldset>
            <legend className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-400">
              Personnages
            </legend>
            <div className="flex flex-wrap gap-1.5">
              {options.personnages.map((o) => (
                <button
                  key={o.nom}
                  type="button"
                  aria-pressed={gouts.personnages.includes(o.nom)}
                  onClick={() => basculer("personnages", o.nom)}
                  className={puce(gouts.personnages.includes(o.nom))}
                  title={o.calibre === "icone" ? "Icône de la série" : "Personnage très recherché"}
                >
                  {o.nom}
                </button>
              ))}
            </div>
          </fieldset>
          <fieldset>
            <legend className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-400">
              Équipages et groupes
            </legend>
            <div className="flex flex-wrap gap-1.5">
              {options.themes.map((o) => (
                <button
                  key={o.slug}
                  type="button"
                  aria-pressed={gouts.themes.includes(o.slug)}
                  onClick={() => basculer("themes", o.slug)}
                  className={puce(gouts.themes.includes(o.slug))}
                >
                  {o.label}
                </button>
              ))}
            </div>
          </fieldset>
          <fieldset>
            <legend className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-400">
              Styles de cartes
            </legend>
            <div className="flex flex-wrap gap-1.5">
              {options.styles.map((o) => (
                <button
                  key={o.cle}
                  type="button"
                  aria-pressed={gouts.styles.includes(o.cle)}
                  onClick={() => basculer("styles", o.cle)}
                  className={puce(gouts.styles.includes(o.cle))}
                >
                  {o.label}
                </button>
              ))}
            </div>
          </fieldset>
          <div>
            <button
              type="button"
              onClick={enregistrer}
              disabled={occupe}
              className="rounded-md bg-amber-300/90 px-3 py-1.5 text-xs font-medium text-ink-950 hover:opacity-90 disabled:opacity-40"
            >
              {occupe ? "…" : "Enregistrer mes goûts"}
            </button>
          </div>
        </div>
      )}
      {erreur && <p className="mt-2 text-[11px] text-rust-400">{erreur}</p>}
    </div>
  );
}

/** Un préféré vu comme une collection à compléter : où tu en es, et la suite. */
function Projet({
  projet,
  budget,
  onOuvrir,
}: {
  projet: ProjetCollection;
  budget: number;
  onOuvrir: (id: number) => void;
}) {
  const { budgets } = useCartesSuivies();
  const [occupe, setOccupe] = useState(false);
  const part = projet.total > 0 ? Math.round((projet.possedees / projet.total) * 100) : 0;
  const prochaine = projet.prochaine;
  const suivie = prochaine ? prochaine.suivie || budgets.has(prochaine.id) : false;

  return (
    <li className="flex flex-col gap-2 rounded-lg border border-ink-700 bg-ink-800/60 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <p className="font-display text-base text-parchment-100">
          {projet.nature === "personnage" ? "★ " : ""}
          {projet.nom}
        </p>
        <p className="tabular font-mono text-xs text-ink-400">
          {projet.possedees} / {projet.total}
        </p>
      </div>
      <div
        className="h-1.5 overflow-hidden rounded-full bg-ink-700"
        role="progressbar"
        aria-valuenow={projet.possedees}
        aria-valuemin={0}
        aria-valuemax={projet.total}
        aria-label={`${projet.possedees} sur ${projet.total} belles versions`}
      >
        <div className="h-full rounded-full bg-amber-300/80" style={{ width: `${part}%` }} />
      </div>
      <p className="text-[11px] leading-relaxed text-ink-400">
        {projet.possedees === projet.total
          ? "Complet : tu as toutes ses belles versions. Bravo !"
          : projet.manquantes_budget > 0
          ? `Il t'en manque ${projet.manquantes_budget} à moins de ${formatEur(budget, 0)} (${formatEur(projet.cout_budget)} en tout)`
          : `Aucune belle version manquante à moins de ${formatEur(budget, 0)}`}
        {projet.hors_budget > 0 &&
          ` · ${projet.hors_budget} au-delà, dès ${formatEur(projet.hors_budget_des ?? 0)}`}
        .
      </p>
      {prochaine && (
        <div className="flex items-center gap-2 rounded-md border border-ink-700 bg-ink-900/60 p-2">
          <button
            type="button"
            onClick={() => onOuvrir(prochaine.id)}
            className="relative h-14 w-10 shrink-0 overflow-hidden rounded-sm bg-ink-950"
            aria-label={`Ouvrir la fiche de ${prochaine.display_name}`}
          >
            <VisuelCarte src={prochaine.image_url} alt={prochaine.display_name} sizes="40px" repli={() => null} />
          </button>
          <div className="min-w-0 flex-1">
            <p className="text-[10px] uppercase tracking-wide text-ink-400">Pour continuer</p>
            <p className="truncate text-xs text-parchment-100">{prochaine.display_name}</p>
            <p className="tabular font-mono text-[11px] text-parchment-100/80">
              {prochaine.price_eur !== null ? formatEur(prochaine.price_eur) : "—"}
              {prochaine.visuel ? <span className="font-sans text-ink-400"> · {prochaine.visuel}</span> : null}
            </p>
          </div>
          <button
            type="button"
            disabled={suivie || occupe}
            onClick={async () => {
              setOccupe(true);
              try {
                await suivre(prochaine.id, prochaine.price_eur !== null ? Math.ceil(prochaine.price_eur) : null);
              } finally {
                setOccupe(false);
              }
            }}
            className="shrink-0 rounded-md border border-amber-300/50 px-2 py-1 text-[11px] text-amber-200 hover:bg-amber-300/10 disabled:opacity-60"
          >
            {suivie ? "★ Suivie" : "☆ Suivre"}
          </button>
        </div>
      )}
    </li>
  );
}
