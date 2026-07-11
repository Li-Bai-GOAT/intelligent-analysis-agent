import { type InputHTMLAttributes, forwardRef } from 'react'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, className = '', ...props }, ref) => {
    return (
      <div className="flex flex-col gap-1.5">
        {label && <label className="text-xs font-medium text-text-secondary">{label}</label>}
        <input
          ref={ref}
          className={`w-full px-3 py-2.5 bg-bg-elevated border border-border rounded-lg text-text-primary text-sm
            placeholder:text-text-muted transition-all duration-150
            focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/30
            ${error ? 'border-error' : ''}
            ${className}`}
          {...props}
        />
        {error && <span className="text-xs text-error">{error}</span>}
      </div>
    )
  },
)

Input.displayName = 'Input'
