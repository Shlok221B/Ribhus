export type IWhatsAppDraftStatus = "pending" | "opened" | "sent" | "skip";

export interface IWhatsAppRecipient {
  id: string;
  name: string;
  phone: string;
  note?: string | null;
}

export interface IWhatsAppDraftsPayload {
  type: "ribhus_whatsapp";
  title?: string;
  template?: string;
  recipients: IWhatsAppRecipient[];
}

export interface IWhatsAppDraftsState {
  template: string;
  statuses: Record<string, IWhatsAppDraftStatus>;
}

const FENCE_RE = /```ribhus-whatsapp\s*([\s\S]*?)```/i;
const PHONE_RE =
  /(?:\+?\d{1,3}[\s-]*)?(?:\(?\d{2,5}\)?[\s-]*)?\d[\d\s-]{7,16}\d/g;

export const DEFAULT_WHATSAPP_TEMPLATE = `Hey {{name}} team!

Could you share availability and total price for us?

Thanks!`;

const normalizePhoneDigits = (raw: string): string | null => {
  const digits = raw.replace(/\D/g, "");
  if (digits.length < 10 || digits.length > 15) return null;
  // India mobiles often listed as 10 digits without country code
  if (digits.length === 10) return `91${digits}`;
  if (digits.length === 11 && digits.startsWith("0")) {
    return `91${digits.slice(1)}`;
  }
  return digits;
};

const recipientId = (phone: string, name: string, index: number): string => {
  const digits = phone.replace(/\D/g, "") || `row-${index}`;
  const slug = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 40);
  return `${digits}:${slug || "contact"}`;
};

const cleanName = (raw: string): string =>
  raw
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[*_`#]/g, "")
    .replace(/\s+/g, " ")
    .trim();

export const applyWhatsAppTemplate = (
  template: string,
  recipient: Pick<IWhatsAppRecipient, "name" | "phone" | "note">,
): string => {
  const name = recipient.name?.trim() || "there";
  const phone = recipient.phone?.trim() || "";
  const note = recipient.note?.trim() || "";
  return template
    .replaceAll("{{name}}", name)
    .replaceAll("{{phone}}", phone)
    .replaceAll("{{note}}", note)
    .replaceAll("[property name]", name)
    .replaceAll("[Property name]", name);
};

export const buildWhatsAppLink = (
  phone: string,
  message: string,
): string | null => {
  const digits = normalizePhoneDigits(phone);
  if (!digits) return null;
  const text = message.trim();
  const base = `https://wa.me/${digits}`;
  if (!text) return base;
  return `${base}?text=${encodeURIComponent(text)}`;
};

const coerceRecipient = (
  raw: Record<string, unknown>,
  index: number,
): IWhatsAppRecipient | null => {
  const phoneRaw = String(
    raw.phone ?? raw.number ?? raw.mobile ?? raw.whatsapp ?? "",
  ).trim();
  const digits = normalizePhoneDigits(phoneRaw);
  if (!digits) return null;
  const name = cleanName(
    String(raw.name ?? raw.contact ?? raw.title ?? raw.stay ?? `Contact ${index + 1}`),
  );
  const noteRaw = raw.note ?? raw.evidence ?? raw.source ?? null;
  const note =
    noteRaw == null || noteRaw === ""
      ? null
      : String(noteRaw).trim().slice(0, 240);
  return {
    id: recipientId(digits, name, index),
    name: name || `Contact ${index + 1}`,
    phone: digits,
    note,
  };
};

export const parseWhatsAppFence = (
  markdown: string | null | undefined,
): IWhatsAppDraftsPayload | null => {
  if (!markdown) return null;
  const match = FENCE_RE.exec(markdown);
  if (!match) return null;
  try {
    const parsed = JSON.parse(match[1] ?? "") as Partial<IWhatsAppDraftsPayload> & {
      contacts?: Record<string, unknown>[];
    };
    const rows = parsed.recipients ?? parsed.contacts;
    if (!Array.isArray(rows)) return null;
    const recipients = rows
      .map((row, index) =>
        coerceRecipient((row ?? {}) as Record<string, unknown>, index),
      )
      .filter((row): row is IWhatsAppRecipient => row != null);
    if (recipients.length === 0) return null;
    return {
      type: "ribhus_whatsapp",
      title:
        typeof parsed.title === "string" && parsed.title.trim()
          ? parsed.title.trim()
          : undefined,
      template:
        typeof parsed.template === "string" && parsed.template.trim()
          ? parsed.template
          : undefined,
      recipients,
    };
  } catch {
    return null;
  }
};

/** Heuristic: markdown tables / lines that include a phone number. */
export const parsePhonesFromMarkdown = (
  markdown: string | null | undefined,
): IWhatsAppDraftsPayload | null => {
  if (!markdown) return null;
  const withoutFence = markdown.replace(FENCE_RE, "").trim();
  if (!withoutFence) return null;

  const recipients: IWhatsAppRecipient[] = [];
  const seen = new Set<string>();

  const push = (name: string, phoneRaw: string, note?: string) => {
    const digits = normalizePhoneDigits(phoneRaw);
    if (!digits || seen.has(digits)) return;
    seen.add(digits);
    const cleaned = cleanName(name) || `Contact ${recipients.length + 1}`;
    recipients.push({
      id: recipientId(digits, cleaned, recipients.length),
      name: cleaned,
      phone: digits,
      note: note?.trim() || null,
    });
  };

  const lines = withoutFence.split(/\r?\n/);
  for (const line of lines) {
    if (!line.includes("|") && !PHONE_RE.test(line)) continue;
    PHONE_RE.lastIndex = 0;
    const phones = line.match(PHONE_RE) ?? [];
    if (phones.length === 0) continue;

    if (line.includes("|")) {
      const cells = line
        .split("|")
        .map((cell) => cell.trim())
        .filter((cell) => cell.length > 0 && !/^:?-{2,}:?$/.test(cell));
      if (cells.length < 2) continue;
      // Skip header-ish rows
      const joined = cells.join(" ").toLowerCase();
      if (
        joined.includes("contact number") ||
        (joined.includes("phone") && joined.includes("stay")) ||
        (cells[0]?.toLowerCase() === "stay" && cells[1]?.toLowerCase().includes("contact"))
      ) {
        continue;
      }
      const phoneCell =
        cells.find((cell) => normalizePhoneDigits(cell)) ?? phones[0] ?? "";
      const nameCell =
        cells.find(
          (cell) =>
            cell !== phoneCell &&
            !normalizePhoneDigits(cell) &&
            cell.length > 1 &&
            !/^https?:\/\//i.test(cell),
        ) ?? cells[0] ?? "";
      const noteCell = cells.find(
        (cell) =>
          cell !== phoneCell &&
          cell !== nameCell &&
          cell.length > 8,
      );
      push(nameCell, phoneCell, noteCell);
      continue;
    }

    // Non-table line: "Name — +91 …" / "Name: +91 …"
    const phone = phones[0] ?? "";
    const namePart = line
      .replace(phone, " ")
      .replace(/[-–—:|]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    if (namePart.length >= 2) push(namePart, phone);
  }

  if (recipients.length < 2) return null;
  return {
    type: "ribhus_whatsapp",
    title: "WhatsApp drafts",
    recipients,
  };
};

export const extractWhatsAppDrafts = (
  markdown: string | null | undefined,
): { payload: IWhatsAppDraftsPayload | null; rest: string } => {
  if (!markdown) return { payload: null, rest: "" };
  const fenced = parseWhatsAppFence(markdown);
  const rest = markdown.replace(FENCE_RE, "").trim();
  if (fenced) return { payload: fenced, rest };
  const heuristic = parsePhonesFromMarkdown(rest);
  return { payload: heuristic, rest };
};

const storageKeyFor = (scope: string): string =>
  `ribhus:wa-drafts:${scope || "default"}`;

export const loadWhatsAppDraftsState = (
  scope: string,
  payload: IWhatsAppDraftsPayload,
): IWhatsAppDraftsState => {
  const fallback: IWhatsAppDraftsState = {
    template: payload.template?.trim() || DEFAULT_WHATSAPP_TEMPLATE,
    statuses: {},
  };
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(storageKeyFor(scope));
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<IWhatsAppDraftsState>;
    return {
      template:
        typeof parsed.template === "string" && parsed.template.trim()
          ? parsed.template
          : fallback.template,
      statuses:
        parsed.statuses && typeof parsed.statuses === "object"
          ? (parsed.statuses as Record<string, IWhatsAppDraftStatus>)
          : {},
    };
  } catch {
    return fallback;
  }
};

export const saveWhatsAppDraftsState = (
  scope: string,
  state: IWhatsAppDraftsState,
): void => {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(storageKeyFor(scope), JSON.stringify(state));
  } catch {
    // ignore quota / private mode
  }
};

export const countByStatus = (
  recipients: IWhatsAppRecipient[],
  statuses: Record<string, IWhatsAppDraftStatus>,
): Record<IWhatsAppDraftStatus, number> => {
  const counts: Record<IWhatsAppDraftStatus, number> = {
    pending: 0,
    opened: 0,
    sent: 0,
    skip: 0,
  };
  for (const row of recipients) {
    const status = statuses[row.id] ?? "pending";
    counts[status] += 1;
  }
  return counts;
};
