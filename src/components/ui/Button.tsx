import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

// Canonical Button primitive for the Edify shell.
//
// Replaces the hand-rolled `bg-emerald-500 hover:brightness-110` patterns
// scattered across pages. Five variants, three sizes, optional leading
// icon, loading state, and href→Link polymorphism so the same component
// is used for actions and navigation links.

export type ButtonVariant =
  | "primary"   // edify brand fill — the page's main action
  | "secondary" // soft fill — a peer action that's not the page's main CTA
  | "ghost"     // no fill — for toolbar/inline actions
  | "danger"    // destructive intent
  | "link";     // text-only, underline-on-hover

export type ButtonSize = "sm" | "md" | "lg";

const SIZE: Record<ButtonSize, string> = {
  sm: "h-7 px-2.5 text-[11.5px] gap-1.5 rounded-md",
  md: "h-9 px-3.5 text-body gap-1.5 rounded-lg",
  lg: "h-11 px-5 text-[13.5px] gap-2 rounded-xl",
};

const VARIANT: Record<ButtonVariant, string> = {
  primary:
    "bg-[var(--color-edify-primary)] text-white font-semibold " +
    "hover:brightness-110 active:brightness-95 " +
    "focus-visible:outline-2 focus-visible:outline-offset-2 " +
    "focus-visible:outline-[var(--color-edify-primary)]",
  secondary:
    "bg-[var(--color-edify-soft)] text-[var(--color-edify-dark)] font-semibold " +
    "border border-[var(--color-edify-border)] " +
    "hover:bg-[color-mix(in_oklab,var(--color-edify-soft)_70%,white)] " +
    "focus-visible:outline-2 focus-visible:outline-offset-2 " +
    "focus-visible:outline-[var(--color-edify-primary)]",
  ghost:
    "bg-transparent text-[var(--color-edify-text)] font-semibold " +
    "hover:bg-[var(--color-edify-soft)]/60 " +
    "focus-visible:outline-2 focus-visible:outline-offset-2 " +
    "focus-visible:outline-[var(--color-edify-primary)]",
  danger:
    "bg-rose-600 text-white font-semibold " +
    "hover:bg-rose-700 active:bg-rose-800 " +
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-600",
  link:
    "bg-transparent text-[var(--color-edify-primary)] font-semibold underline-offset-2 " +
    "hover:underline px-0 h-auto py-0 rounded-none",
};

const BASE =
  "inline-flex items-center justify-center whitespace-nowrap " +
  "transition-colors disabled:opacity-55 disabled:cursor-not-allowed " +
  "disabled:pointer-events-none";

type IconComponent = React.ComponentType<{ size?: number; className?: string }>;

type CommonProps = {
  variant?: ButtonVariant;
  size?: ButtonSize;
  Icon?: IconComponent;
  TrailingIcon?: IconComponent;
  loading?: boolean;
  fullWidth?: boolean;
  children?: ReactNode;
  className?: string;
};

type ButtonAsButton = CommonProps &
  Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children" | "className"> & {
    href?: undefined;
  };

type ButtonAsLink = CommonProps & {
  href: string;
  target?: string;
  rel?: string;
  prefetch?: boolean;
  // Forbid button-only attrs so the discriminated union is honest.
  onClick?: React.MouseEventHandler<HTMLAnchorElement>;
};

export type ButtonProps = ButtonAsButton | ButtonAsLink;

export const Button = forwardRef<HTMLButtonElement | HTMLAnchorElement, ButtonProps>(
  function Button(props, ref) {
    const {
      variant = "primary",
      size = "md",
      Icon,
      TrailingIcon,
      loading = false,
      fullWidth = false,
      className,
      children,
      ...rest
    } = props as CommonProps & Record<string, unknown>;

    const sizeClasses = variant === "link" ? "" : SIZE[size];
    const classes = cn(
      BASE,
      sizeClasses,
      VARIANT[variant],
      fullWidth && "w-full",
      className,
    );

    const inner = (
      <>
        {loading ? (
          <Loader2 size={size === "lg" ? 14 : 12} className="animate-spin" />
        ) : Icon ? (
          <Icon size={size === "lg" ? 14 : 12} />
        ) : null}
        {children}
        {!loading && TrailingIcon ? (
          <TrailingIcon size={size === "lg" ? 14 : 12} />
        ) : null}
      </>
    );

    if ("href" in props && props.href != null) {
      // Next.js Link rendering — keeps client-side navigation.
      const { href, target, rel, prefetch, onClick, ...linkRest } = rest as {
        href: string;
        target?: string;
        rel?: string;
        prefetch?: boolean;
        onClick?: React.MouseEventHandler<HTMLAnchorElement>;
      };
      return (
        <Link
          ref={ref as React.Ref<HTMLAnchorElement>}
          href={href}
          target={target}
          rel={rel}
          prefetch={prefetch}
          onClick={onClick}
          className={classes}
          {...(linkRest as Record<string, unknown>)}
        >
          {inner}
        </Link>
      );
    }

    return (
      <button
        ref={ref as React.Ref<HTMLButtonElement>}
        type={(rest as ButtonHTMLAttributes<HTMLButtonElement>).type ?? "button"}
        disabled={loading || (rest as ButtonHTMLAttributes<HTMLButtonElement>).disabled}
        className={classes}
        {...(rest as ButtonHTMLAttributes<HTMLButtonElement>)}
      >
        {inner}
      </button>
    );
  },
);
