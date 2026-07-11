import { Component, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('ErrorBoundary caught:', error, info)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="h-screen flex items-center justify-center bg-bg-base p-8">
          <div className="max-w-lg w-full bg-bg-surface border border-border rounded-xl p-6">
            <h2 className="text-lg font-semibold text-error mb-3">渲染出错</h2>
            <pre className="text-xs text-text-secondary bg-bg-base rounded-lg p-4 overflow-auto max-h-60">
              {this.state.error?.message}
              {'\n\n'}
              {this.state.error?.stack}
            </pre>
            <button
              onClick={() => { localStorage.clear(); location.reload() }}
              className="mt-4 px-4 py-2 bg-accent text-bg-base rounded-lg text-sm font-medium cursor-pointer"
            >
              清除数据并刷新
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
