import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  TextareaHTMLAttributes,
} from "react";
import { cn } from "@/lib/utils";

interface IButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "danger";
}

export const Button = ({
  className,
  variant = "primary",
  type = "button",
  ...props
}: IButtonProps) => (
  <button
    type={type}
    className={cn(
      "inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-40",
      variant === "primary" &&
        "bg-primary text-primary-foreground shadow-sm hover:brightness-110",
      variant === "secondary" &&
        "border border-border bg-secondary text-secondary-foreground hover:bg-accent",
      variant === "ghost" &&
        "border border-border bg-transparent text-foreground hover:bg-accent",
      variant === "danger" &&
        "border border-destructive/40 bg-transparent text-destructive hover:bg-destructive/10",
      className,
    )}
    {...props}
  />
);

interface ICardProps {
  children: ReactNode;
  className?: string;
}

export const Card = ({ children, className }: ICardProps) => (
  <div
    className={cn(
      "rounded-2xl border border-border/80 bg-card/90 shadow-[0_12px_40px_-24px_rgba(0,0,0,0.65)] backdrop-blur-sm",
      className,
    )}
  >
    {children}
  </div>
);

export const Field = ({
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement>) => (
  <input
    className={cn(
      "w-full rounded-xl border border-input/70 bg-background/70 px-3.5 py-2.5 text-sm text-foreground placeholder:text-muted-foreground/55 transition-colors focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
      className,
    )}
    {...props}
  />
);

export const TextArea = ({
  className,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement>) => (
  <textarea
    className={cn(
      "w-full resize-y rounded-xl border border-input/70 bg-background/70 px-3.5 py-3 text-sm text-foreground placeholder:text-muted-foreground/55 transition-colors focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
      className,
    )}
    {...props}
  />
);

interface IBadgeProps {
  children: ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger" | "info";
  className?: string;
}

export const Badge = ({
  children,
  tone = "neutral",
  className,
}: IBadgeProps) => (
  <span
    className={cn(
      "inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-medium tracking-wide",
      tone === "neutral" && "bg-accent text-muted-foreground",
      tone === "success" && "bg-success/15 text-success",
      tone === "warning" && "bg-warning/15 text-warning",
      tone === "danger" && "bg-destructive/15 text-destructive",
      tone === "info" && "bg-info/15 text-info",
      className,
    )}
  >
    {children}
  </span>
);

interface IPageHeaderProps {
  title: string;
  description?: string;
  action?: ReactNode;
}

export const PageHeader = ({ title, description, action }: IPageHeaderProps) => (
  <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
    <div className="min-w-0">
      <h2 className="text-xl font-semibold tracking-tight text-foreground md:text-2xl">
        {title}
      </h2>
      {description ? (
        <p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted-foreground">
          {description}
        </p>
      ) : null}
    </div>
    {action ? <div className="shrink-0">{action}</div> : null}
  </div>
);

export const statusTone = (
  status: string,
): IBadgeProps["tone"] => {
  if (status === "completed" || status === "connected" || status === "live") {
    return "success";
  }
  if (status === "failed" || status === "cancelled" || status === "killed") {
    return "danger";
  }
  if (status === "awaiting_approval") return "warning";
  if (status === "running" || status === "queued") return "info";
  return "neutral";
};
