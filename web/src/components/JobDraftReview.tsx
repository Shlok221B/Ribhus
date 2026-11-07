import { useState } from "react";
import type { IJobApplication } from "@/lib/api";
import { Button, Field, TextArea } from "@/components/ui";

interface IJobDraftReviewProps {
  application: IJobApplication;
  locked?: boolean;
  onChange: (patch: Partial<IJobApplication>) => void;
}

const resumeReview = (application: IJobApplication) => {
  const note = application.tailor_note ?? "";
  const change = application.resume_change?.trim()
    || (/base resume/i.test(note)
      ? "Base resume attached. Nothing in the LaTeX was changed."
      : note || "Resume attached.");
  const skip = note.match(/Summary (?:was )?left as written[^\n]*/i)?.[0] ?? "";
  if (skip && !/left as written/i.test(change)) return `${change}\n${skip}`;
  return change;
};

const emailWhy = (application: IJobApplication) => {
  if (application.email_why?.trim()) return application.email_why.trim();
  const place =
    application.company && application.company !== "Company" ? application.company : "this company";
  const title =
    application.role && application.role !== "Role" ? application.role : "this role";
  return `Written for the ${title} opening at ${place}. It says who you are, cites facts already on your resume, and asks for a short conversation.`;
};

export const JobDraftReview = ({ application, locked = false, onChange }: IJobDraftReviewProps) => {
  const [editing, setEditing] = useState(false);
  const resume = resumeReview(application);
  const why = emailWhy(application);

  return (
    <div className="mt-4 flex flex-col gap-4">
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Resume</p>
        <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-foreground">{resume}</p>
      </div>
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Email</p>
        <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{why}</p>
        <p className="mt-1 text-sm font-medium text-foreground">{application.subject}</p>
        <p className="mt-2 text-sm text-foreground">
          To {application.to || "no address yet"}
        </p>
        <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-foreground">
          {application.body}
        </p>
      </div>
      <Button
        variant="ghost"
        className="w-full sm:w-auto"
        disabled={locked}
        aria-expanded={editing}
        onClick={() => setEditing((open) => !open)}
      >
        {editing ? "Hide edits" : "Edit draft"}
      </Button>
      {editing ? (
        <div className="grid gap-3">
          {application.emails?.length ? (
            <div className="flex flex-wrap gap-2">
              {application.emails.map((email) => (
                <button
                  key={email}
                  type="button"
                  className="rounded-full border border-border px-2.5 py-1 text-xs text-foreground hover:bg-accent"
                  disabled={locked}
                  onClick={() => onChange({ to: email })}
                >
                  {email}
                </button>
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">No email was on this opening. Add one, or drop it.</p>
          )}
          <label className="block text-sm text-foreground">
            To
            <Field
              className="mt-1.5"
              type="email"
              aria-label={`Contact email for ${application.role || "opening"}`}
              value={application.to}
              placeholder="name@company.com"
              disabled={locked}
              onChange={(event) => onChange({ to: event.target.value })}
            />
          </label>
          <label className="block text-sm text-foreground">
            Subject
            <Field
              className="mt-1.5"
              aria-label={`Subject for ${application.role || "opening"}`}
              value={application.subject}
              disabled={locked}
              onChange={(event) => onChange({ subject: event.target.value })}
            />
          </label>
          <label className="block text-sm text-foreground">
            Email
            <TextArea
              className="mt-1.5"
              rows={8}
              aria-label={`Email for ${application.role || "opening"}`}
              value={application.body}
              disabled={locked}
              onChange={(event) => onChange({ body: event.target.value })}
            />
          </label>
        </div>
      ) : null}
    </div>
  );
};
