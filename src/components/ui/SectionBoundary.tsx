"use client";

import { Component, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

// Component-level error boundary for a single dashboard section.
//
// Why this exists: dashboards compose many independent backend-driven cards.
// Without isolation, one card whose surface returns an off-spec payload (e.g.
// a `live` response with an unexpectedly missing array) throws during render
// and the *whole* page falls to the route-segment error.tsx — a blank cockpit
// for one bad card. Wrapping each backend section in a SectionBoundary keeps
// the failure local: that card shows a compact, retryable notice while every
// other section renders normally.
//
// It catches render errors from its children, including async server-component
// children passed in via the `children` slot.

type Props = {
  children: ReactNode;
  // Human label for the section, used in the fallback copy ("Couldn't load X").
  label?: string;
};

type State = { hasError: boolean };

export class SectionBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  private reset = () => this.setState({ hasError: false });

  render() {
    if (!this.state.hasError) return this.props.children;
    const what = this.props.label ?? "this section";
    return (
      <section className="card p-3.5">
        <div className="flex items-center gap-2.5">
          <span className="h-8 w-8 shrink-0 rounded-lg bg-rose-100 text-rose-700 grid place-items-center">
            <AlertTriangle size={15} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-[12.5px] font-bold leading-tight">Couldn&apos;t load {what}</p>
            <p className="text-[11px] muted leading-snug">The rest of this page is unaffected. Try reloading just this part.</p>
          </div>
          <button
            type="button"
            onClick={this.reset}
            className="btn btn-sm shrink-0"
            aria-label={`Retry loading ${what}`}
          >
            <RefreshCw size={11} />
            Retry
          </button>
        </div>
      </section>
    );
  }
}
