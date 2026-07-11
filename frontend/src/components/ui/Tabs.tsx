interface Tab {
  key: string
  label: string
  icon?: React.ReactNode
}

interface TabsProps {
  tabs: Tab[]
  active: string
  onChange: (key: string) => void
  size?: 'sm' | 'md'
}

export function Tabs({ tabs, active, onChange, size = 'md' }: TabsProps) {
  const sizeClass = size === 'sm' ? 'text-xs px-3 py-1.5' : 'text-sm px-4 py-2'

  return (
    <div className="flex gap-1 bg-bg-base rounded-lg p-1">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          onClick={() => onChange(tab.key)}
          className={`flex items-center gap-1.5 rounded-md transition-all duration-150 font-medium cursor-pointer ${sizeClass}
            ${active === tab.key
              ? 'bg-bg-elevated text-text-primary shadow-sm'
              : 'text-text-muted hover:text-text-secondary'
            }`}
        >
          {tab.icon}
          {tab.label}
        </button>
      ))}
    </div>
  )
}
