import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { label } from "./api";

export function useSaved<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      return (
        JSON.parse(localStorage.getItem(`tour.${key}`) || "null") ?? initial
      );
    } catch {
      return initial;
    }
  });
  useEffect(() => {
    localStorage.setItem(`tour.${key}`, JSON.stringify(value));
  }, [key, value]);
  return [value, setValue] as const;
}
const paths: Record<string, string> = {
  library: "M4 4h6v6H4z M14 4h6v6h-6z M4 14h6v6H4z M14 14h6v6h-6z",
  compass: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M16 8l-2.5 5.5L8 16l2.5-5.5z",
  cases: "M8 5V3h8v2 M3 7h18v13H3z M3 12h18 M10 11v3h4v-3",
  weekly: "M5 4h14v17l-7-4-7 4z",
  settings:
    "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M12 2v3 M12 19v3 M2 12h3 M19 12h3 M5 5l2 2 M17 17l2 2 M5 19l2-2 M17 7l2-2",
  plus: "M12 5v14 M5 12h14",
  upload: "M12 16V3 M7 8l5-5 5 5 M4 15v6h16v-6",
  search: "M10.5 3a7.5 7.5 0 1 0 0 15 7.5 7.5 0 0 0 0-15 M16 16l5 5",
  arrow: "M4 12h16 M14 6l6 6-6 6",
  check: "M5 12l4 4 10-10",
  close: "M6 6l12 12 M6 18L18 6",
  file: "M5 2h9l5 5v15H5z M14 2v6h5 M8 12h8 M8 16h6",
  chat: "M3 4h18v13H9l-6 4z M7 8h10 M7 12h7",
  image: "M3 3h18v18H3z M3 16l5-5 4 4 3-3 6 6 M15 7h.01",
  refresh:
    "M20 7v5h-5 M4 17v-5h5 M5 8a8 8 0 0 1 13-3l2 3 M4 16l2 3a8 8 0 0 0 13-3",
  copy: "M8 8h13v13H8z M16 8V3H3v13h5",
  download: "M12 3v13 M7 11l5 5 5-5 M3 17v4h18v-4",
  clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 7v5l3 2",
  alert: "M12 3L2 21h20z M12 9v5 M12 17h.01",
  chevron: "M9 5l7 7-7 7",
  save: "M3 3h15l3 3v15H3z M7 3v6h10V3 M7 21v-8h10v8",
  link: "M10 13l4-4 M8 16l-2 2a4 4 0 0 1-6-6l4-4 M16 8l2-2a4 4 0 0 1 6 6l-4 4",
  user: "M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M4 21v-3a8 8 0 0 1 16 0v3",
  spark: "M12 2l3 7 7 3-7 3-3 7-3-7-7-3 7-3z",
};
export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name] || paths.file} />
    </svg>
  );
}
export function Badge({ value, tone }: { value: unknown; tone?: string }) {
  const text = label(value);
  return (
    <span
      className={`badge ${tone || (/PASS|COMPLETED|STORED|READY|EXTRACTED/.test(String(value)) ? "green" : /FAIL|BLOCK|NEEDS|PARTIAL|PENDING/.test(String(value)) ? "amber" : "neutral")}`}
    >
      {text}
    </span>
  );
}
export function Field({
  label: caption,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="field">
      <span>{caption}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}
export function Empty({
  icon = "library",
  title,
  text,
  children,
}: {
  icon?: string;
  title: string;
  text: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Icon name={icon} size={28} />
      </span>
      <h3>{title}</h3>
      <p>{text}</p>
      {children}
    </div>
  );
}
export function Modal({
  title,
  subtitle,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section
        className={`modal ${wide ? "wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header className="modal-header">
          <div>
            <h2>{title}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <button className="icon-button" aria-label="关闭" onClick={onClose}>
            <Icon name="close" />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}
export function SectionHead({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children?: ReactNode;
}) {
  return (
    <div className="section-head">
      <div>
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </div>
      <div className="actions">{children}</div>
    </div>
  );
}
