import Markdown from "react-markdown";
import { ExternalLink, MapPin } from "lucide-react";
import { cn } from "@/lib/utils";

interface IMarkdownProps {
  children: string;
  className?: string;
}

const isGoogleMapsUrl = (href?: string | null): boolean =>
  Boolean(href && /google\.[^/\s]+\/maps/i.test(href));

/** Turn bare http(s) URLs into markdown links; leave existing [text](url) alone. */
export const linkifyBareUrls = (input: string): string => {
  if (!input) return input;
  const token = /(\[[^\]]*]\([^)]+\)|https?:\/\/[^\s<]+)/g;
  let last = 0;
  let out = "";
  let match: RegExpExecArray | null;
  while ((match = token.exec(input)) !== null) {
    out += input.slice(last, match.index);
    const tok = match[0];
    if (tok.startsWith("[")) {
      out += tok;
    } else {
      let url = tok;
      let trail = "";
      while (url.length > 0 && /[.,;:!?)\]}>]$/.test(url)) {
        trail = `${url.slice(-1)}${trail}`;
        url = url.slice(0, -1);
      }
      const label = isGoogleMapsUrl(url) ? "Open in Google Maps" : url;
      out += `[${label}](${url})${trail}`;
    }
    last = match.index + tok.length;
  }
  out += input.slice(last);
  return out;
};

export const MarkdownBody = ({ children, className }: IMarkdownProps) => (
  <div className={cn("prose-result", className)}>
    <Markdown
      components={{
        h1: ({ children: c }) => (
          <h1 className="mt-6 text-xl font-semibold tracking-tight text-foreground first:mt-0">
            {c}
          </h1>
        ),
        h2: ({ children: c }) => (
          <h2 className="mt-6 border-b border-border/60 pb-2 text-lg font-semibold tracking-tight text-foreground first:mt-0">
            {c}
          </h2>
        ),
        h3: ({ children: c }) => (
          <h3 className="mt-5 text-base font-semibold text-foreground first:mt-0">
            {c}
          </h3>
        ),
        p: ({ children: c }) => (
          <p className="mt-3 text-sm leading-relaxed text-foreground/90 first:mt-0">
            {c}
          </p>
        ),
        ul: ({ children: c }) => (
          <ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-relaxed text-foreground/90">
            {c}
          </ul>
        ),
        ol: ({ children: c }) => (
          <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm leading-relaxed text-foreground/90">
            {c}
          </ol>
        ),
        li: ({ children: c }) => <li className="pl-0.5">{c}</li>,
        strong: ({ children: c }) => (
          <strong className="font-semibold text-foreground">{c}</strong>
        ),
        em: ({ children: c }) => (
          <em className="italic text-foreground/90">{c}</em>
        ),
        a: ({ href, children: c }) => {
          if (isGoogleMapsUrl(href)) {
            return (
              <a
                href={href}
                target="_blank"
                rel="noreferrer"
                aria-label="Open in Google Maps"
                className="my-1 inline-flex max-w-full items-center gap-1.5 rounded-lg border border-info/35 bg-info/10 px-2.5 py-1.5 text-xs font-medium text-info transition-colors hover:bg-info/20"
              >
                <MapPin className="h-3.5 w-3.5 shrink-0" aria-hidden />
                <span className="truncate">Open in Google Maps</span>
                <ExternalLink className="h-3 w-3 shrink-0 opacity-70" aria-hidden />
              </a>
            );
          }
          return (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="text-info underline-offset-2 hover:underline"
            >
              {c}
            </a>
          );
        },
        code: ({ className: codeClass, children: c }) => {
          const block = Boolean(codeClass);
          if (block) {
            return (
              <code className="font-mono text-[12px] text-foreground/90">
                {c}
              </code>
            );
          }
          return (
            <code className="rounded-md bg-background/80 px-1.5 py-0.5 font-mono text-[12px] text-primary">
              {c}
            </code>
          );
        },
        pre: ({ children: c }) => (
          <pre className="mt-3 overflow-x-auto rounded-xl border border-border bg-background/70 p-3 text-[12px]">
            {c}
          </pre>
        ),
        blockquote: ({ children: c }) => (
          <blockquote className="mt-3 border-l-2 border-primary/40 pl-3 text-sm text-muted-foreground">
            {c}
          </blockquote>
        ),
        hr: () => <hr className="my-5 border-border/70" />,
      }}
    >
      {linkifyBareUrls(children)}
    </Markdown>
  </div>
);
