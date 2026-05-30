import { forwardRef, useId, type SelectHTMLAttributes, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

// Canonical native <select>. Uses the OS picker on each platform —
// fast, accessible, no JS overhead. For multi-select / search-as-you-type,
// reach for a Combobox component (not part of this primitive set).

const SIZE = {
  sm: "h-8 pl-2.5 pr-8 text-[12px] rounded-md",
  md: "h-10 pl-3 pr-9 text-[13px] rounded-lg",
  lg: "h-12 pl-3.5 pr-10 text-body-lg rounded-xl",
} as const;

export type SelectSize = keyof typeof SIZE;

export type SelectOption = {
  value: string;
  label: string;
  disabled?: boolean;
};

export type SelectProps = Omit<
  SelectHTMLAttributes<HTMLSelectElement>,
  "size" | "className" | "children"
> & {
  label?: ReactNode;
  helper?: ReactNode;
  error?: ReactNode;
  options: ReadonlyArray<SelectOption>;
  placeholder?: string;
  selectSize?: SelectSize;
  className?: string;
  wrapperClassName?: string;
};

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  {
    label,
    helper,
    error,
    options,
    placeholder,
    selectSize = "md",
    className,
    wrapperClassName,
    id: idProp,
    required,
    disabled,
    value,
    defaultValue,
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

      <div className="relative">
        <select
          ref={ref}
          id={id}
          required={required}
          disabled={disabled}
          aria-invalid={!!error}
          aria-describedby={describedBy}
          value={value}
          defaultValue={defaultValue ?? (placeholder && value === undefined ? "" : undefined)}
          className={cn(
            "appearance-none w-full bg-white border transition-colors outline-none",
            "border-[var(--color-edify-border)] text-[var(--color-edify-text)]",
            "focus:outline-2 focus:outline-offset-0",
            "focus:outline-[var(--color-edify-primary)]",
            error && "border-rose-400 focus:outline-rose-500",
            disabled && "opacity-60 bg-[var(--color-edify-soft)]/40",
            SIZE[selectSize],
            className,
          )}
          {...rest}
        >
          {placeholder ? (
            <option value="" disabled>
              {placeholder}
            </option>
          ) : null}
          {options.map((o) => (
            <option key={o.value} value={o.value} disabled={o.disabled}>
              {o.label}
            </option>
          ))}
        </select>
        <ChevronDown
          size={14}
          className="pointer-events-none absolute top-1/2 -translate-y-1/2 right-2.5 text-[var(--color-edify-muted)]"
        />
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
