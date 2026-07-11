interface ContextRingProps {
  percent: number
  tokens?: number
  maxTokens?: number
}

export function ContextRing({ percent, tokens = 0, maxTokens = 120000 }: ContextRingProps) {
  const r = 15.9
  const circumference = 2 * Math.PI * r
  const dashArray = `${(percent / 100) * circumference} ${circumference}`

  const color = percent >= 80 ? 'var(--color-error)' : percent >= 60 ? 'var(--color-warning)' : 'var(--color-accent)'

  return (
    <div
      className="relative w-9 h-9 shrink-0 cursor-default"
      title={`上下文: ${(tokens / 1000).toFixed(1)}K / ${(maxTokens / 1000).toFixed(0)}K tokens (${percent.toFixed(1)}%)`}
    >
      <svg viewBox="0 0 36 36" className="w-full h-full -rotate-90">
        <circle cx="18" cy="18" r={r} fill="none" stroke="var(--color-bg-muted)" strokeWidth="3" />
        <circle
          cx="18"
          cy="18"
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="3"
          strokeDasharray={dashArray}
          strokeLinecap="round"
          className="transition-all duration-300"
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center text-[10px] font-mono text-text-muted">
        {Math.round(percent)}%
      </span>
    </div>
  )
}
