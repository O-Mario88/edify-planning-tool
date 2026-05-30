import { forwardRef, useId, type TextareaHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/utils";

// Canonical Textarea. Same label/helper/error contract as Input.

export type TextareaProps = Omit<
  TextareaHTMLAttributes<HTMLTextAreaElement>,
  "className"
> & {
  label?: ReactNode;
  helper?: ReactNode;
  error?: ReactNode;
  className?: string;
  wrapperClassName?: string;
};

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  {
    label,
    helper,
    error,
    className,
    wrapperClassName,
    id: idProp,
    required,
    disabled,
    rows = 3,
    ...rest
  },
  ref,
) {
  const reactId = useId();
  const id = idProp ?? reactId;
  const describedBy = error ? `${id}-err` : helper ? `${id}-help` : undefined;

  return (
    <div className={cn("flex flex-col gap-1", wrapperClassName)}>
      {label ? (
        <label
          htmlFor={id}
          className="text-[11.5px] font-semibold text-[var(--color-edify-text)]"
        >
          {label}
          {required ? <span className="text-rose-600 ml-0.5">*</span> : null}
        </label>
      ) : null}

      <textarea
        ref={ref}
        id={id}
        required={required}
        disabled={disabled}
        rows={rows}
        aria-invalid={!!error}
        aria-describedby={describedBy}
        className={cn(
          "bg-white border outline-none transition-colors",
          "border-[var(--color-edify-border)] rounded-lg",
          "px-3 py-2 text-[13px] leading-relaxed resize-y",
          "placeholder:text-[var(--color-edify-muted)]/70",
          "focus:outline-2 focus:outline-offset-0",
          "focus:outline-[var(--color-edify-primary)]",
          error && "border-rose-400 focus:outline-rose-500",
          disabled && "opacity-60 bg-[var(--color-edify-soft)]/40",
          className,
        )}
        {...rest}
      />

      {error ? (
        <p
          id={`${id}-err`}
          className="text-[11px] font-semibold text-rose-600"
          role="alert"
        >
          {error}
        </p>
      ) : helper ? (
        <p
          id={`${id}-help`}
          className="text-[11px] text-[var(--color-edify-muted)]"
        >
          {helper}
        </p>
      ) : null}
    </div>
  );
});
