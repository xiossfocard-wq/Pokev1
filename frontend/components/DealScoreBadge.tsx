interface DealScoreBadgeProps {
  score: number | null;
  size?: number;
}

function scoreColor(score: number): string {
  if (score >= 75) return "#5FBE8D"; // moss-400
  if (score >= 50) return "#F0A94E"; // ember-400
  return "#E5646A"; // rust-400
}

export default function DealScoreBadge({ score, size = 56 }: DealScoreBadgeProps) {
  if (score === null) {
    return (
      <div
        className="flex items-center justify-center rounded-full border border-ink-600 text-[10px] text-ink-600 font-mono"
        style={{ width: size, height: size }}
        title="Pas encore de prix de référence trouvé pour cette annonce"
      >
        N/A
      </div>
    );
  }

  const radius = (size - 6) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - Math.min(Math.max(score, 0), 100) / 100);
  const color = scoreColor(score);

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} role="img" aria-label={`Score de bonne affaire : ${Math.round(score)} sur 100`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="#252934" strokeWidth={4} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={4}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className="transition-[stroke-dashoffset] duration-500 ease-out"
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center font-mono text-sm font-semibold" style={{ color }}>
        {Math.round(score)}
      </div>
    </div>
  );
}
