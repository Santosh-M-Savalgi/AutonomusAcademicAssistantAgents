import { forwardRef, type InputHTMLAttributes } from 'react'
import { cn } from '@/utils/cn'
import { AlertCircle } from 'lucide-react'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
  helperText?: string
}

const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, label, error, helperText, id, ...props }, ref) => {
    const inputId = id || label?.toLowerCase().replace(/\s+/g, '-')

    return (
      <div className="flex flex-col gap-1.5">
        {label && (
          <label htmlFor={inputId} className="text-sm font-medium text-text-primary">
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          className={cn(
            'h-10 w-full px-3 py-2 text-sm rounded-md bg-surface border text-text-primary placeholder:text-text-muted transition-all duration-200',
            'focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary',
            error
              ? 'border-danger focus:border-danger focus:ring-danger'
              : 'border-surface-border hover:border-text-muted',
            className
          )}
          {...props}
        />
        {error && (
          <span className="flex items-center gap-1 text-xs text-danger">
            <AlertCircle className="h-3 w-3" />
            {error}
          </span>
        )}
        {helperText && !error && (
          <span className="text-xs text-text-muted">{helperText}</span>
        )}
      </div>
    )
  }
)

Input.displayName = 'Input'

export { Input }
export type { InputProps }
