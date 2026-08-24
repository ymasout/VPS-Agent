import Link from "next/link";
import React, { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";

type Tone = "neutral" | "info" | "success" | "warning" | "danger";

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="ui-page-header">
      <div>
        {eyebrow && <p className="ui-page-header__eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {description && <p className="ui-page-header__description">{description}</p>}
      </div>
      {actions && <div className="ui-page-header__actions">{actions}</div>}
    </header>
  );
}

export function Panel({
  children,
  className = "",
  as = "section",
}: {
  children: ReactNode;
  className?: string;
  as?: "section" | "article" | "div";
}) {
  const Component = as;
  return <Component className={`ui-panel ${className}`.trim()}>{children}</Component>;
}

export function StatusBadge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`ui-status ui-status--${tone}`}><span aria-hidden="true" />{children}</span>;
}

export function ButtonLink({
  href,
  children,
  tone = "primary",
}: {
  href: string;
  children: ReactNode;
  tone?: "primary" | "secondary";
}) {
  return <Link className={`ui-button ui-button--${tone}`} href={href}>{children}</Link>;
}

export const IconButton = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { label: string }
>(function IconButton({ label, children, ...props }, ref) {
  return <button className="ui-icon-button" aria-label={label} ref={ref} type="button" {...props}>{children}</button>;
});

export function StateView({
  state,
  title,
  description,
  children,
}: {
  state: "empty" | "loading" | "error" | "forbidden" | "unavailable";
  title: string;
  description: string;
  children?: ReactNode;
}) {
  const urgent = state === "error" || state === "forbidden";
  const marks = { empty: "–", loading: "…", error: "!", forbidden: "×", unavailable: "?" };
  return (
    <Panel className={`ui-state ui-state--${state}`}>
      <div className="ui-state__mark" aria-hidden="true">{marks[state]}</div>
      <div>
        <h2>{title}</h2>
        <p>{description}</p>
        {children}
      </div>
      <span className="sr-only" role={urgent ? "alert" : "status"}>{title}</span>
    </Panel>
  );
}
