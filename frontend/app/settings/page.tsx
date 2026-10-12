"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchSettings, updateSettings, type AppSettings } from "@/lib/api";

export default function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    fetchSettings()
      .then(setSettings)
      .catch((err) => setLoadError(err instanceof Error ? err.message : String(err)));
  }, []);

  function set<K extends keyof AppSettings>(key: K, value: AppSettings[K]) {
    setSettings((s) => (s ? { ...s, [key]: value } : s));
    setSaved(false);
    setSaveError(null);
  }

  async function save() {
    if (!settings) return;
    setSaving(true);
    setSaveError(null);
    try {
      setSettings(await updateSettings(settings));
      setSaved(true);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <header className="sticky top-0 z-20 border-b border-ink-800 bg-ink-950/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-2.5">
          <Link href="/" className="font-display text-lg leading-none text-parchment-100">
            Pokéradar
          </Link>
          <span className="text-ink-600">/</span>
          <span className="text-sm text-parchment-100">Réglages</span>
          <Link
            href="/"
            className="ml-auto rounded-md border border-ink-700 px-2.5 py-1.5 text-xs text-parchment-100 transition-colors hover:border-ember-500"
          >
            ← Retour au radar
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-2xl px-4 pb-16 pt-6">
        {loadError && (
          <div className="rounded-md border border-rust-500/40 bg-rust-500/10 px-3 py-2 text-xs text-rust-400">
            Impossible de charger les réglages. [{loadError}]
          </div>
        )}

        {!settings && !loadError && (
          <div className="flex flex-col gap-3">
            <div className="skeleton h-24" />
            <div className="skeleton h-24" />
            <div className="skeleton h-40" />
          </div>
        )}

        {settings && (
          <div className="flex flex-col gap-4">
            <Section title="Ce que tu vois">
              <Field
                label="Prix minimum affiché (€)"
                hint="Les annonces à ce prix ou en dessous sont masquées. Les cartes à 1 € sont presque toujours des lots ou des titres trompeurs. Mettre 0 pour tout revoir."
                value={settings.min_listing_price}
                onChange={(v) => set("min_listing_price", v)}
                min={0}
                max={100}
                step={0.5}
              />
            </Section>

            <Section title="Alertes">
              <Field
                label="Seuil de notification (score / 100)"
                hint="Une notification Telegram ou email part quand une annonce dépasse ce score. Les annonces au prix incertain ne dépassent jamais 60."
                value={settings.deal_score_threshold}
                onChange={(v) => set("deal_score_threshold", v)}
                min={0}
                max={100}
              />
              <Field
                label="Intervalle de vérification (minutes)"
                hint="Fréquence des cycles de collecte. Sur l'hébergement gratuit, le serveur s'endort entre deux visites : la fréquence réelle dépend surtout de l'automate de réveil."
                value={settings.check_interval_minutes}
                onChange={(v) => set("check_interval_minutes", v)}
                min={5}
                max={180}
              />
            </Section>

            <Section
              title="Pondération du score"
              intro="Les trois valeurs sont ramenées à un total de 100 % ; pas besoin qu'elles somment exactement."
            >
              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="Marge" value={settings.margin_weight} onChange={(v) => set("margin_weight", v)} min={0} max={1} step={0.05} />
                <Field label="Qualité" value={settings.quality_weight} onChange={(v) => set("quality_weight", v)} min={0} max={1} step={0.05} />
                <Field label="Vendeur" value={settings.seller_weight} onChange={(v) => set("seller_weight", v)} min={0} max={1} step={0.05} />
              </div>
            </Section>

            {saveError && (
              <div className="rounded-md border border-rust-500/40 bg-rust-500/10 px-3 py-2 text-xs text-rust-400">
                Enregistrement impossible. [{saveError}]
              </div>
            )}

            <button
              onClick={save}
              disabled={saving}
              className="rounded-md bg-ember-500 px-4 py-2.5 text-sm font-medium text-ink-950 transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {saving ? "Enregistrement…" : saved ? "Enregistré ✓" : "Enregistrer"}
            </button>
          </div>
        )}
      </main>
    </>
  );
}

function Section({ title, intro, children }: { title: string; intro?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-ink-700 bg-ink-800/60 p-4">
      <h2 className="font-display text-lg text-parchment-100">{title}</h2>
      {intro && <p className="mt-0.5 text-xs text-ink-600">{intro}</p>}
      <div className="mt-3 flex flex-col gap-4">{children}</div>
    </section>
  );
}

function Field({
  label,
  hint,
  value,
  onChange,
  min,
  max,
  step = 1,
}: {
  label: string;
  hint?: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step?: number;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm text-parchment-100">{label}</span>
      {hint && <span className="mb-1.5 block text-xs leading-relaxed text-ink-600">{hint}</span>}
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
        className="tabular w-full rounded-md border border-ink-700 bg-ink-900 px-3 py-2 font-mono text-sm text-parchment-100 focus:border-ember-500 focus:outline-none"
      />
    </label>
  );
}
