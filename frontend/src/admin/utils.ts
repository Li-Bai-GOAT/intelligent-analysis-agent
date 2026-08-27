export function formatDate(value?: string | null) {
  if (!value) return '暂无记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export const inputClass = 'h-10 w-full border border-border bg-bg-elevated px-3 text-sm leading-5 text-text-primary outline-none transition-colors placeholder:text-text-muted focus:border-accent'
export const searchInputClass = 'h-10 w-full border border-border bg-bg-elevated pl-3 pr-10 text-sm leading-5 text-text-primary outline-none transition-colors placeholder:text-text-muted focus:border-accent'
export const textareaClass = `${inputClass} min-h-28 resize-y leading-6`

export const adminTableClass = 'w-full border-collapse text-left text-sm leading-5'
export const adminTableHeaderCellClass = 'h-11 px-4 py-0 align-middle text-xs font-medium leading-5 text-text-secondary'
export const adminTableCellClass = 'px-4 py-2.5 align-middle text-sm leading-5'
export const adminTableActionCellClass = `${adminTableCellClass} text-right`
