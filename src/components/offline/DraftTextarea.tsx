"use client";

// Draft-saving textarea (spec layer #9) — drop-in replacement for a plain
// <textarea> in any field form (minutes, debrief, notes). Autosaves locally and
// shows a "Draft saved" status so staff trust it survives a dropped connection.

import { useEffect } from "react";
import { Check, RotateCcw } from "lucide-react";
import { useDraft } from "@/lib/offline/useDraft";

export function DraftTextarea({
  draftKey,
  initial = "",
  placeholder,
  rows = 6,
  name,
  className,
  onValueChange,
}: {
  draftKey: string;
  initial?: string;
  placeholder?: string;
  rows?: number;
  name?: string;
  className?: string;
  onValueChange?: (v: string) => void;
}) {
  const { value, setValue, savedAt, restored, clear } = useDraft<string>(draftKey, initial);

  useEffect(() => {
    onValueChange?.(value);
  }, [value, onValueChange]);

  return (
    <div>
      <textarea
        name={name}
        rows={rows}
        value={value}
        placeholder={placeholder}
        onChange={(e) => setValue(e.target.value)}
        className={className ?? "w-full rounded-lg border border-slate-200 bg-white p-2.5 text-sm dark:border-slate-700 dark:bg-slate-900"}
      />
      <div className="mt-1 flex items-center justify-between text-[11px] text-slate-400">
        <span className="inline-flex items-center gap-1">
          {savedAt && (
            <>
              <Check size={11} className="text-emerald-500" /> Draft saved locally
            </>
          )}
          {restored && <span className="ml-1 text-amber-500">· restored unsent draft</span>}
        </span>
        {value && (
          <button type="button" onClick={() => { setValue(""); clear(); }} className="inline-flex items-center gap-1 hover:text-slate-600">
            <RotateCcw size={11} /> Clear
          </button>
        )}
      </div>
    </div>
  );
}
