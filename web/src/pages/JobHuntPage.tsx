import { useEffect, useState, type FormEvent } from "react";
import { api, type IJobApplication, type IJobStatus } from "@/lib/api";
import { Badge, Button, Card, Field, PageHeader, TextArea } from "@/components/ui";

const JobHuntPage = () => {
  const [status, setStatus] = useState<IJobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [resumeText, setResumeText] = useState("");
  const [url, setUrl] = useState("");
  const [jd, setJd] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<IJobApplication | null>(null);
  const [approved, setApproved] = useState(false);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [gmailNote, setGmailNote] = useState<string | null>(null);

  const load = async () => {
    const next = await api.jobStatus();
    setStatus(next);
    setError(null);
    return next;
  };

  useEffect(() => {
    void load().catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "Failed to load job hunt");
    });
  }, []);

  useEffect(() => {
    return () => {
      if (pdfUrl) URL.revokeObjectURL(pdfUrl);
    };
  }, [pdfUrl]);

  const selectApplication = async (app: IJobApplication) => {
    setSelectedId(app.id);
    setDraft(app);
    setApproved(false);
    setGmailNote(null);
    if (pdfUrl) {
      URL.revokeObjectURL(pdfUrl);
      setPdfUrl(null);
    }
    if (!app.pdf_ready) return;
    try {
      const blob = await api.jobPdf(app.id);
      setPdfUrl(URL.createObjectURL(blob));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the PDF");
    }
  };

  const handleSaveResume = async (event?: FormEvent) => {
    event?.preventDefault();
    const tex = resumeText.trim();
    if (!tex || busy) return;
    setBusy("resume");
    setError(null);
    try {
      await api.saveJobResume(tex);
      setResumeText("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the resume");
    } finally {
      setBusy(null);
    }
  };

  const handleFile = async (file: File | undefined) => {
    if (!file) return;
    const text = await file.text();
    setResumeText(text);
  };

  const handlePrepare = async (event: FormEvent) => {
    event.preventDefault();
    const link = url.trim();
    const pasted = jd.trim();
    if (busy || (!link && pasted.length < 80)) return;
    setBusy("prepare");
    setError(null);
    try {
      const created = await api.prepareJob({ url: link, text: pasted });
      setUrl("");
      setJd("");
      await load();
      await selectApplication(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not prepare that job");
    } finally {
      setBusy(null);
    }
  };

  const handleConnect = async () => {
    setBusy("gmail");
    setError(null);
    setGmailNote("A Brave window is opening. Sign in to Google there, then come back.");
    try {
      const result = await api.connectJobGmail();
      setGmailNote(
        result.logged_in
          ? "Gmail is signed in for this dashboard session."
          : "Gmail window closed before sign-in finished.",
      );
      await load();
    } catch (err) {
      setGmailNote(null);
      setError(err instanceof Error ? err.message : "Gmail sign-in failed");
    } finally {
      setBusy(null);
    }
  };

  const handleSend = async () => {
    if (!draft || !approved || busy) return;
    setBusy("send");
    setError(null);
    try {
      const sent = await api.sendJob(draft.id, {
        to: draft.to,
        subject: draft.subject,
        body: draft.body,
      });
      setDraft(sent);
      setApproved(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Send failed");
    } finally {
      setBusy(null);
    }
  };

  const applications = status?.applications ?? [];

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader
        title="Job hunt"
        description="Tailor a LaTeX resume to a posting and send it through Gmail only after you approve."
      />

      <Card className="p-5">
        <h3 className="text-base font-semibold text-foreground">How to use</h3>
        <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm leading-relaxed text-muted-foreground">
          <li>
            Install Tectonic (
            <code className="text-foreground">brew install tectonic</code>) so the
            resume can compile to a PDF.
          </li>
          <li>Save your base .tex resume below. Upload the file or paste it.</li>
          <li>
            Connect Gmail and sign in in the browser window. Nothing is sent yet.
          </li>
          <li>
            Paste a public job link, or paste the description if the page needs a
            login.
          </li>
          <li>
            Review the email and PDF, edit them, check the approval box, then send.
          </li>
        </ol>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
          Set <code className="text-foreground">RIBHUS_API_KEY</code> if you want the
          wording tailored. Without it, the PDF is your saved resume.
        </p>
      </Card>

      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-base font-semibold text-foreground">Base resume</h3>
            <Badge tone={!status ? "neutral" : status.resume_saved ? "success" : "warning"}>
              {!status ? "…" : status.resume_saved ? "saved" : "needed"}
            </Badge>
          </div>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            Upload the <span className="font-medium text-foreground">.tex</span> file
            you want every application to start from.
            {status?.model_ready
              ? " Tailoring uses your configured model and keeps existing employers and dates."
              : status
                ? " Set RIBHUS_API_KEY to tailor wording. Without it, the PDF is your base resume."
                : ""}
          </p>
          <form className="mt-4 flex flex-col gap-3" onSubmit={(event) => void handleSaveResume(event)}>
            <input
              type="file"
              accept=".tex,text/plain"
              aria-label="Upload LaTeX resume"
              className="block w-full text-sm text-muted-foreground file:mr-3 file:rounded-lg file:border file:border-border file:bg-secondary file:px-3 file:py-2 file:text-sm file:text-foreground"
              onChange={(event) => void handleFile(event.target.files?.[0])}
            />
            <TextArea
              rows={6}
              value={resumeText}
              placeholder="Or paste the .tex contents"
              aria-label="LaTeX resume"
              onChange={(event) => setResumeText(event.target.value)}
            />
            <Button type="submit" disabled={busy !== null || !resumeText.trim()}>
              {busy === "resume" ? "Saving…" : "Save resume"}
            </Button>
          </form>
        </Card>

        <Card className="p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-base font-semibold text-foreground">Gmail</h3>
            <Badge
              tone={
                !status
                  ? "neutral"
                  : status.email_killed
                    ? "danger"
                    : status.email_enabled
                      ? "success"
                      : "warning"
              }
            >
              {!status
                ? "…"
                : status.email_killed
                  ? "killed"
                  : status.email_enabled
                    ? "enabled"
                    : "disabled"}
            </Badge>
          </div>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            Sends go through Gmail in Chromium, with the PDF attached. Nothing is sent
            from the prepare step.
          </p>
          <p className="mt-2 truncate text-[11px] text-muted-foreground/70" title={status?.email_profile}>
            {status?.email_profile}
          </p>
          {gmailNote ? (
            <p className="mt-3 text-sm text-foreground" role="status">
              {gmailNote}
            </p>
          ) : null}
          <Button
            className="mt-4"
            variant="secondary"
            disabled={busy !== null || status?.email_killed === true}
            onClick={() => void handleConnect()}
          >
            {busy === "gmail" ? "Waiting for sign-in…" : "Connect Gmail"}
          </Button>
          {status && !status.tectonic ? (
            <p className="mt-3 text-sm text-destructive">
              Tectonic is missing, so PDFs cannot compile. Install it with brew install tectonic.
            </p>
          ) : null}
        </Card>
      </div>

      <Card className="p-5">
        <h3 className="text-base font-semibold text-foreground">New application</h3>
        <form className="mt-4 flex flex-col gap-3" onSubmit={(event) => void handlePrepare(event)}>
          <Field
            type="url"
            value={url}
            placeholder="https://jobs.example.com/role"
            aria-label="Job posting URL"
            onChange={(event) => setUrl(event.target.value)}
          />
          <label className="block text-sm text-foreground">
            Job description
            <TextArea
              className="mt-1.5"
              rows={6}
              value={jd}
              placeholder="Paste the role, company, and requirements when the link is behind a login"
              aria-label="Job description"
              onChange={(event) => setJd(event.target.value)}
            />
          </label>
          <p className="text-xs leading-relaxed text-muted-foreground">
            A public link is enough. If the page has no text, paste the description
            instead. A few sentences is enough.
          </p>
          <Button
            type="submit"
            className="w-full sm:w-auto"
            disabled={
              busy !== null ||
              !status?.resume_saved ||
              (!url.trim() && jd.trim().length < 80)
            }
          >
            {busy === "prepare" ? "Preparing…" : "Prepare"}
          </Button>
        </form>
      </Card>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,16rem)_minmax(0,1fr)]">
        <Card className="p-3">
          <h3 className="px-2 py-2 text-sm font-semibold text-foreground">Applications</h3>
          {applications.length === 0 ? (
            <p className="px-2 pb-2 text-sm text-muted-foreground">None yet.</p>
          ) : (
            <ul className="space-y-1">
              {applications.map((app) => (
                <li key={app.id}>
                  <button
                    type="button"
                    className={`w-full rounded-xl px-3 py-2.5 text-left text-sm transition-colors ${
                      selectedId === app.id
                        ? "bg-primary/12 text-foreground"
                        : "text-muted-foreground hover:bg-accent hover:text-foreground"
                    }`}
                    onClick={() => void selectApplication(app)}
                  >
                    <div className="truncate font-medium">{app.role || app.company}</div>
                    <div className="truncate text-xs">{app.company}</div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        {draft ? (
          <Card className="p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="text-base font-semibold text-foreground">
                  {draft.role}
                  {draft.company && draft.company !== "Company" ? ` · ${draft.company}` : ""}
                </h3>
                {draft.url ? (
                  <a
                    href={draft.url}
                    className="mt-1 block truncate text-xs text-primary underline-offset-2 hover:underline"
                    target="_blank"
                    rel="noreferrer"
                  >
                    {draft.url}
                  </a>
                ) : (
                  <p className="mt-1 text-xs text-muted-foreground">Pasted description</p>
                )}
              </div>
              <Badge tone={draft.status === "sent" ? "success" : draft.status === "failed" ? "danger" : "warning"}>
                {draft.status}
              </Badge>
            </div>

            {draft.tailor_note ? (
              <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{draft.tailor_note}</p>
            ) : null}
            {draft.error ? (
              <p className="mt-2 text-sm text-destructive" role="alert">
                {draft.error}
              </p>
            ) : null}

            {draft.keywords.length > 0 ? (
              <div className="mt-4 flex flex-wrap gap-2">
                {draft.keywords.map((word) => (
                  <Badge key={word}>{word}</Badge>
                ))}
              </div>
            ) : null}

            <div className="mt-4 grid gap-4">
              <label className="block text-sm text-foreground">
                To
                {draft.emails.length > 0 ? (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {draft.emails.map((email) => (
                      <button
                        key={email}
                        type="button"
                        className="rounded-full border border-border px-2.5 py-1 text-xs text-foreground hover:bg-accent"
                        onClick={() => {
                          setApproved(false);
                          setDraft({ ...draft, to: email });
                        }}
                      >
                        {email}
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="mt-1 text-xs text-muted-foreground">
                    No email was on the posting. Add one if you have it.
                  </p>
                )}
                <Field
                  className="mt-1.5"
                  type="email"
                  aria-label="Contact email"
                  value={draft.to}
                  placeholder="name@company.com"
                  onChange={(event) => {
                    setApproved(false);
                    setDraft({ ...draft, to: event.target.value });
                  }}
                />
              </label>
              <label className="block text-sm text-foreground">
                Subject
                <Field
                  className="mt-1.5"
                  aria-label="Email subject"
                  value={draft.subject}
                  onChange={(event) => {
                    setApproved(false);
                    setDraft({ ...draft, subject: event.target.value });
                  }}
                />
              </label>
              <label className="block text-sm text-foreground">
                Email
                <TextArea
                  className="mt-1.5"
                  rows={14}
                  aria-label="Email body"
                  value={draft.body}
                  onChange={(event) => {
                    setApproved(false);
                    setDraft({ ...draft, body: event.target.value });
                  }}
                />
              </label>
            </div>

            {pdfUrl ? (
              <iframe
                title={`Resume PDF for ${draft.company}`}
                src={pdfUrl}
                className="mt-4 h-80 w-full rounded-xl border border-border bg-background sm:h-[32rem]"
              />
            ) : null}

            <label className="mt-4 flex items-start gap-2 text-sm text-foreground">
              <input
                type="checkbox"
                className="mt-1"
                checked={approved}
                disabled={draft.status === "sent" || !draft.pdf_ready}
                onChange={(event) => setApproved(event.target.checked)}
              />
              <span>I approve sending this email and the attached PDF.</span>
            </label>
            <Button
              className="mt-4"
              disabled={
                busy !== null ||
                !approved ||
                draft.status === "sent" ||
                !draft.pdf_ready ||
                !draft.to.includes("@")
              }
              onClick={() => void handleSend()}
            >
              {busy === "send" ? "Sending…" : draft.status === "sent" ? "Sent" : "Send through Gmail"}
            </Button>
          </Card>
        ) : (
          <Card className="flex items-center p-6 text-sm text-muted-foreground">
            Prepare a job link to review the email and PDF here.
          </Card>
        )}
      </div>
    </div>
  );
};

export default JobHuntPage;
