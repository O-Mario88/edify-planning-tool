import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/utils";

// Canonical text Input.
//
// Renders label + control + optional helper/error in one wrapper so
// forms across the app share the same label position, error tone, and
// focus ring. Drop-in for native <input>; pass `error` to flip into
// error state with the error message rendered below.

export type InputSize = "sm" | "md" | "lg";

const SIZE: Record<InputSize, string> = {
  sm: "h-8 px-2.5 text-[12px] rounded-md",
  md: "h-10 px-3 text-[13px] rounded-lg",
  lg: "h-12 px-3.5 text-body-lg rounded-xl",
};

export type InputProps = Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "size" | "className"
> & {
  label?: ReactNode;
  helper?: ReactNode;
  error?: ReactNode;
  inputSize?: InputSize;
  leadingIcon?: React.ComponentType<{ size?: number; className?: string }>;
  trailingSlot?: ReactNode;
  className?: string;
  wrapperClassName?: string;
};

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  {
    label,
    helper,
    error,
    inputSize = "md",
    leadingIcon: LeadingIcon,
    trailingSlot,
    className,
    wrapperClassName,
    id: idProp,
    required,
    disabled,
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

      <div
        className={cn(
          "relative flex items-center bg-white border transition-colors",
          "border-[var(--color-edify-border)]",
          "focus-within:outline-2 focus-within:outline-offset-0",
          "focus-within:outline-[var(--color-edify-primary)]",
          error && "border-rose-400 focus-within:outline-rose-500",
          disabled && "opacity-60 bg-[var(--color-edify-soft)]/40",
          SIZE[inputSize].split(" ").filter((c) => c.startsWith("rounded")).join(" "),
        )}
      >
        {LeadingIcon ? (
          <span className="pl-2.5 text-[var(--color-edify-muted)] grid place-items-center">
            <LeadingIcon size={14} />
          </span>
        ) : null}
        <input
          ref={ref}
          id={id}
          required={required}
          disabled={disabled}
          aria-invalid={!!error}
          aria-describedby={describedBy}
          className={cn(
            "flex-1 min-w-0 bg-transparent outline-none",
            "placeholder:text-[var(--color-edify-muted)]/70",
            SIZE[inputSize],
            LeadingIcon && "pl-2",
            trailingSlot && "pr-2",
            className,
          )}
          {...rest}
        />
        {trailingSlot ? (
          <span className="pr-2.5 text-[var(--color-edify-muted)]">{trailingSlot}</span>
        ) : null}
      </div>

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
