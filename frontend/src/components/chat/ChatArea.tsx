import { MessageList } from './MessageList'
import { InputArea } from './InputArea'
import { PreviewConfirm } from './PreviewConfirm'

export function ChatArea() {
  return (
    <div className="flex flex-col flex-1 min-w-0 bg-bg-base">
      <MessageList />
      <PreviewConfirm />
      <InputArea />
    </div>
  )
}
