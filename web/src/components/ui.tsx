import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  TextareaHTMLAttributes,
} from "react";
import { Star } from "lucide-react";
import { cn } from "@/lib/utils";

export const BOT_BG: Record<string, string> = {
  copper: "bg-[color:var(--palette-red)]",
  blue: "bg-[color:var(--palette-blue)]",
  gold: "bg-[color:var(--palette-gold)]",
  verdigris: "bg-[color:var(--palette-verdigris)]",
  rose: "bg-[color:var(--palette-rose)]",
  info: "bg-[color:var(--palette-blue)]",
};

const AVATAR_SIZE = {
  sm: "h-7 w-7 rounded-[10px]",
  md: "h-10 w-10 rounded-xl",
  lg: "h-14 w-14 rounded-2xl",
} as const;

const EYE_SIZE = {
  sm: "h-2 w-[3px] rounded-full",
  md: "h-2.5 w-1 rounded-full",
  lg: "h-3.5 w-1.5 rounded-full",
} as const;

interface IBotAvatarProps {
  color?: string;
  size?: keyof typeof AVATAR_SIZE;
  primary?: boolean;
  live?: boolean;
  className?: string;
}

/** Grok-style squircle avatar: bot color + two dash eyes. */
export const BotAvatar = ({
  color,
  size = "md",
  primary,
  live,
  className,
}: IBotAvatarProps) => (
  <span
    className={cn(
      "relative inline-flex shrink-0 items-center justify-center shadow-[inset_0_-4px_12px_rgba(0,0,0,0.18)] transition-transform duration-200",
      AVATAR_SIZE[size],
      BOT_BG[color ?? "copper"] ?? BOT_BG.copper,
      live && "status-dot-live",
      className,
    )}
    aria-hidden
  >
    <span className={cn("flex", size === "lg" ? "gap-2" : "gap-1.5")}>
      <span className={cn("bg-black/60", EYE_SIZE[size])} />
      <span className={cn("bg-black/60", EYE_SIZE[size])} />
    </span>
    {primary ? (
      <span className="absolute -bottom-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full bg-background">
        <Star className="h-2.5 w-2.5 fill-warning text-warning" />
      </span>
    ) : null}
  </span>
);

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
      "press-scale inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-40",
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
      "rounded-2xl border border-border/80 bg-card/90 shadow-[0_12px_40px_-24px_rgba(0,0,0,0.65)] backdrop-blur-sm transition-[border-color,box-shadow,background-color] duration-200",
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

/** Three bouncing dots — Grok-style "thinking" indicator. */
export const TypingDots = ({ className }: { className?: string }) => (
  <span className={cn("typing-dots", className)} aria-label="Working">
    <span />
    <span />
    <span />
  </span>
);

interface IStatusDotProps {
  colorClass: string;
  live?: boolean;
  className?: string;
}

/** Bot color dot; pulses with a ring when the bot is working/waiting. */
export const StatusDot = ({ colorClass, live, className }: IStatusDotProps) => (
  <span
    className={cn(
      "relative inline-block h-2.5 w-2.5 shrink-0 rounded-full transition-transform duration-200",
      colorClass,
      live && "status-dot-live scale-110",
      className,
    )}
    aria-hidden
  />
);

export const Spinner = ({ className }: { className?: string }) => (
  <span
    className={cn(
      "inline-block h-4 w-4 rounded-full border-2 border-muted-foreground/30 border-t-primary",
      className,
    )}
    style={{ animation: "spin-slow 0.8s linear infinite" }}
    aria-label="Loading"
  />
);
