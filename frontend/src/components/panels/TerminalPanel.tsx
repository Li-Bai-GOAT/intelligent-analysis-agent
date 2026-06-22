export function TerminalPanel() {
  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-3 py-2 bg-[#161b22] border-b border-[#30363d]">
        <div className="flex gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-[#ff5f56]" />
          <span className="w-2.5 h-2.5 rounded-full bg-[#ffbd2e]" />
          <span className="w-2.5 h-2.5 rounded-full bg-[#27c93f]" />
        </div>
        <span className="text-[11px] text-[#8b949e] flex-1 text-center font-mono">agent_sandbox</span>
      </div>
      <div
        id="terminal-body"
        className="flex-1 overflow-y-auto p-3 bg-[#0d1117] font-mono text-xs text-[#c9d1d9] leading-relaxed"
      >
        <div className="text-[#58a6ff]">
          <span className="text-[#7ee787]">user</span>
          <span className="text-[#8b949e]">@</span>
          <span className="text-[#ff7b72]">sandbox</span>
          <span className="text-[#8b949e]">:~$</span>
          <span className="text-[#f0f6fc] ml-2">等待任务执行...</span>
        </div>
      </div>
    </div>
  )
}
