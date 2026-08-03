"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchSettings, updateSettings, type AppSettings } from "@/lib/api";

export default function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetchSettings().then(setSettings).catch(() => {});
  }, []);

  if (!settings) {
    return (
      <main className="mx-auto max-w-lg px-4 py-6 text-sm text-ink-600">
        Chargement des réglages…
      </main>
    );
  }

  function set<K extends keyof AppSettings>(key: K, value: AppSettings[K]) {
    setSettings((s) => (s ? { ...s, [key]: value } : s));
    setSaved(false);
  }

  async function save() {
    if (!settings) return;
    setSaving(true);
    try {
      const updated = await updateSettings(settings);
      setSettings(updated);
      setSaved(true);
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="mx-auto max-w-lg px-4 py-6">
      <Link href="/" className="text-xs text-ink-600 hover:text-ember-400">
        ← Retour au dashboard
      </Link>
      <h1 className="mb-6 mt-2 font-display text-2xl text-parchment-100">Réglages</h1>

      <div className="flex flex-col gap-5">
        <Field
          label="Seuil de notification (score / 100)"
          hint="Une notification Telegram/email part quand une annonce dépasse ce score."
          value={settings.deal_score_threshold}
          onChange={(v) => set("deal_score_threshold", v)}
          min={0}
          max={100}
        />
        <Field
          label="Intervalle de vérification (minutes)"
          hint="Fréquence des cycles de collecte eBay + Vinted. Redémarre le backend pour appliquer un changement."
          value={settings.check_interval_minutes}
          onChange={(v) => set("check_interval_minutes", v)}
          min={5}
          max={180}
        />

        <div>
          <p className="mb-2 text-sm text-parchment-100">
            Pondération du score de bonne affaire
          </p>
          <p className="mb-3 text-xs text-ink-600">
            Les trois valeurs sont automatiquement ramenées à un total de 100% ;
            pas besoin qu&apos;elles somment exactement.
          </p>
          <div className="flex flex-col gap-3">
            <Field label="Marge" value={settings.margin_weight} onChange={(v) => set("margin_weight", v)} min={0} max={1} step={0.05} />
            <Field label="Qualité (texte + photos)" value={settings.quality_weight} onChange={(v) => set("quality_weight", v)} min={0} max={1} step={0.05} />
            <Field label="Fiabilité vendeur" value={settings.seller_weight} onChange={(v) => set("seller_weight", v)} min={0} max={1} step={0.05} />
          </div>
        </div>

        <button
          onClick={save}
          disabled={saving}
          className="rounded-sm bg-ember-500 px-4 py-2 text-sm font-medium text-ink-950 transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {saving ? "Enregistrement…" : saved ? "Enregistré ✓" : "Enregistrer"}
        </button>
      </div>
    </main>
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
      {hint && <span className="mb-1.5 block text-xs text-ink-600">{hint}</span>}
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full rounded-sm border border-ink-700 bg-ink-800 px-3 py-1.5 font-mono text-sm text-parchment-100 focus:border-ember-500 focus:outline-none"
      />
    </label>
  );
}
