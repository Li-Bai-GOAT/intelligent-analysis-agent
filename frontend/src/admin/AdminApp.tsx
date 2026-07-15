import { BrainCircuit, Boxes, Database, Gauge, PlugZap } from 'lucide-react'
import { Header } from '../components/layout/Header'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'
import type { AdminSection } from './types'
import { OverviewPage } from './pages/OverviewPage'
import { KnowledgePage } from './pages/KnowledgePage'
import { PromptPage } from './pages/PromptPage'
import { SkillsPage } from './pages/SkillsPage'
import { McpsPage } from './pages/McpsPage'

const navigation: Array<{ key: AdminSection; label: string; description: string; icon: typeof Gauge }> = [
  { key: 'overview', label: '运行总览', description: '依赖与配置状态', icon: Gauge },
  { key: 'knowledge', label: '知识库', description: '维护 Agent 知识', icon: Database },
  { key: 'prompt', label: '系统提示词', description: '管理产品经理规则', icon: BrainCircuit },
  { key: 'skills', label: 'Skills', description: 'KunCode 能力包', icon: Boxes },
  { key: 'mcps', label: 'MCP', description: '外部工具服务', icon: PlugZap },
]

function CurrentPage({ section }: { section: AdminSection }) {
  if (section === 'knowledge') return <KnowledgePage />
  if (section === 'prompt') return <PromptPage />
  if (section === 'skills') return <SkillsPage />
  if (section === 'mcps') return <McpsPage />
  return <OverviewPage />
}

export function AdminApp() {
  const user = useAuthStore((state) => state.user)
  const adminTab = useUiStore((state) => state.adminTab)
  const setAdminTab = useUiStore((state) => state.setAdminTab)

  if (!user?.is_admin) {
    return (
      <div className="flex h-screen flex-col bg-bg-base">
        <Header />
        <div className="flex flex-1 items-center justify-center px-6 text-center">
          <div>
            <p className="text-sm font-medium text-text-primary">无法访问管理后台</p>
            <p className="mt-2 text-xs text-text-secondary">当前账号没有管理员权限。</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-screen flex-col bg-bg-base">
      <Header />
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden md:flex-row">
        <aside className="flex shrink-0 flex-col border-b border-border bg-bg-surface md:w-60 md:border-b-0 md:border-r">
          <div className="hidden px-4 pb-2 pt-5 md:block">
            <p className="text-xs font-semibold uppercase text-text-muted">管理工作台</p>
          </div>
          <nav className="flex gap-1 overflow-x-auto px-3 py-2 md:flex-col md:overflow-visible md:py-1" aria-label="管理后台导航">
            {navigation.map(({ key, label, description, icon: Icon }) => {
              const active = adminTab === key
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => setAdminTab(key)}
                  className={`flex min-w-max items-center gap-3 border px-3 py-2.5 text-left transition-colors md:min-w-0 ${
                    active
                      ? 'border-accent/30 bg-accent-subtle text-text-primary'
                      : 'border-transparent text-text-secondary hover:bg-bg-hover hover:text-text-primary'
                  }`}
                >
                  <Icon size={17} className={active ? 'text-accent' : 'text-text-muted'} />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">{label}</span>
                    <span className="hidden truncate text-xs text-text-muted md:block">{description}</span>
                  </span>
                </button>
              )
            })}
          </nav>
          <div className="mt-auto hidden border-t border-border px-4 py-4 text-xs leading-5 text-text-muted md:block">
            配置变更将影响后续 Agent 与沙箱运行。
          </div>
        </aside>

        <main className="min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1440px] px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
            <CurrentPage section={adminTab} />
          </div>
        </main>
      </div>
    </div>
  )
}
