import { FileText, FolderOpen, Terminal } from 'lucide-react'
import { Tabs } from '../ui/Tabs'
import { PlanPanel } from '../panels/PlanPanel'
import { FilesPanel } from '../panels/FilesPanel'
import { TerminalPanel } from '../panels/TerminalPanel'
import { useUiStore } from '../../stores/ui'

const tabs = [
  { key: 'plan', label: '计划', icon: <FileText size={14} /> },
  { key: 'files', label: '文件', icon: <FolderOpen size={14} /> },
  { key: 'terminal', label: '终端', icon: <Terminal size={14} /> },
]

export function RightPanel() {
  const { rightTab, setRightTab } = useUiStore()

  return (
    <aside className="flex flex-col w-[45%] min-w-[300px] bg-bg-surface border-l border-border shrink-0">
      <div className="px-3 py-2 border-b border-border">
        <Tabs tabs={tabs} active={rightTab} onChange={(k) => setRightTab(k as typeof rightTab)} size="sm" />
      </div>
      <div className="flex-1 overflow-hidden">
        {rightTab === 'plan' && <PlanPanel />}
        {rightTab === 'files' && <FilesPanel />}
        {rightTab === 'terminal' && <TerminalPanel />}
      </div>
    </aside>
  )
}
