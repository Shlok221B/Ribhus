import { useState } from "react";
import { Button, TextArea } from "@/components/ui";
import type { IPendingApproval } from "@/lib/api";

interface IClarifyApprovalProps {
  pending: IPendingApproval;
  acting: boolean;
  onAnswer: (answer: string) => void;
  onCancel: () => void;
}

const asChoices = (raw: unknown): string[] => {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((item) => String(item ?? "").trim())
    .filter(Boolean)
    .slice(0, 8);
};

export const ClarifyApproval = ({
  pending,
  acting,
  onAnswer,
  onCancel,
}: IClarifyApprovalProps) => {
  const question = String(pending.arguments?.question ?? "").trim();
  const choices = asChoices(pending.arguments?.choices);
  const [custom, setCustom] = useState("");

  return (
    <div className="space-y-4">
      <div>
        <p className="text-xs font-medium uppercase tracking-wider text-warning">
          Quick question
        </p>
        <p className="mt-2 text-sm leading-relaxed text-foreground">
          {question || "Ribhus needs a quick choice to continue."}
        </p>
      </div>

      {choices.length > 0 ? (
        <div className="flex flex-col gap-2">
          {choices.map((choice, index) => (
            <Button
              key={`${index}-${choice.slice(0, 24)}`}
              type="button"
              variant="secondary"
              disabled={acting}
              className="h-auto min-h-10 w-full justify-start whitespace-normal px-3 py-2.5 text-left"
              onClick={() => onAnswer(choice)}
            >
              <span className="mr-2 shrink-0 text-xs text-muted-foreground">
                {index + 1}.
              </span>
              <span>{choice}</span>
            </Button>
          ))}
        </div>
      ) : null}

      <div className="space-y-2">
        <TextArea
          value={custom}
          onChange={(event) => setCustom(event.target.value)}
          rows={2}
          placeholder="Or type your own answer…"
          aria-label="Custom clarify answer"
          disabled={acting}
        />
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            disabled={acting || !custom.trim()}
            onClick={() => onAnswer(custom.trim())}
          >
            Submit answer
          </Button>
          <Button
            type="button"
            variant="danger"
            disabled={acting}
            onClick={onCancel}
          >
            Skip
          </Button>
        </div>
      </div>
    </div>
  );
};

export default ClarifyApproval;
