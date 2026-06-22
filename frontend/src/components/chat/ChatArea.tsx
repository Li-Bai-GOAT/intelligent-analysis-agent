import { MessageList } from './MessageList'
import { InputArea } from './InputArea'

export function ChatArea() {
  return (
    <div className="flex flex-col flex-1 min-w-0 bg-bg-base">
      <MessageList />
      <InputArea />
    </div>
  )
}
