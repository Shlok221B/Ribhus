import { useEffect, useState, type FormEvent } from "react";
import { api, type IJobApplication, type IJobBatch, type IJobStatus } from "@/lib/api";
import { JobBatchPanel } from "@/components/JobBatchPanel";
import { JobDraftReview } from "@/components/JobDraftReview";
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
  const [batchUrl, setBatchUrl] = useState("");
  const [batchText, setBatchText] = useState("");
  const [batch, setBatch] = useState<IJobBatch | null>(null);
  const [batchApproved, setBatchApproved] = useState(false);
  const [batchProgress, setBatchProgress] = useState<string | null>(null);
  const [batchResult, setBatchResult] = useState<string | null>(null);
  const [showSetup, setShowSetup] = useState(false);

  const load = async () => {
    const next = await api.jobStatus();
    setStatus(next);
    setError(null);
    setBatch((current) => current ?? next.batch ?? null);
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

  const handlePrepareBatch = async (event: FormEvent) => {
    event.preventDefault();
    const link = batchUrl.trim();
    const pasted = batchText.trim();
    if (busy || (!link && pasted.length < 40)) return;
    setBusy("batch");
    setError(null);
    setBatchResult(null);
    setBatchProgress(null);
    setBatchApproved(false);
    try {
      const created = await api.prepareJobBatch({ url: link, text: pasted });
      setBatchUrl("");
      setBatchText("");
      await load();
      setBatch(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not prepare that batch");
    } finally {
      setBusy(null);
    }
  };

  const handleSendBatch = async () => {
    if (!batch || !batchApproved || busy) return;
    setBusy("batch-send");
    setError(null);
    setBatchResult(null);
    try {
      let current = await api.saveJobBatch(
        batch.id,
        batch.applications.map((app) => ({
          id: app.id,
          kept: app.kept !== false,
          to: app.to,
          subject: app.subject,
          body: app.body,
        })),
      );
      setBatch(current);
      let guard = 0;
      while (guard < 12) {
        guard += 1;
        const kept = current.applications.filter((app) => app.kept !== false);
        const sent = kept.filter((app) => app.status === "sent").length;
        setBatchProgress(
          kept.length > 0
            ? `Sending ${Math.min(sent + 1, kept.length)} of ${kept.length}. Gmail pauses between emails.`
            : "Sending…",
        );
        const step = await api.sendJobBatchNext(current.id);
        current = step.batch;
        setBatch(current);
        if (step.stopped) {
          setError(current.error || "Sending stopped.");
          break;
        }
        if (step.finished || !step.sent_id) {
          const sentCount = current.applications.filter((app) => app.status === "sent").length;
          const skipped = current.applications.filter((app) => app.status === "skipped").length;
          setBatchResult(
            skipped > 0
              ? `Sent ${sentCount}. Skipped ${skipped} with no contact email.`
              : `Sent ${sentCount}.`,
          );
          break;
        }
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Send failed");
    } finally {
      setBusy(null);
      setBatchProgress(null);
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
  const setupReady = Boolean(
    status?.resume_saved && status.tectonic && status.email_enabled && !status.email_killed,
  );
  const showSetupCards = !setupReady || showSetup || gmailNote !== null;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader
        title="Job hunt"
        description={
          setupReady
            ? "Paste a link or several openings, then review the drafts before anything is sent."
            : "Save a resume and connect Gmail, then paste a job."
        }
        action={
          setupReady ? (
            <Button variant="ghost" onClick={() => setShowSetup((open) => !open)}>
              {showSetup ? "Hide setup" : "Setup"}
            </Button>
          ) : null
        }
      />

      {showSetupCards ? (
      <>
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
            login. Use Prepare a batch when one link or paste contains several openings.
          </li>
          <li>
            Review the email and PDF, edit them, check the approval box, then send.
            A batch lets you drop drafts, then sends the rest one by one.
          </li>
        </ol>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
          Set <code className="text-foreground">RIBHUS_API_KEY</code> to rewrite the
          summary. Skills already on the resume are reordered to match each posting either way.
        </p>
      </Card>

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
                ? " Set RIBHUS_API_KEY to rewrite the summary. Skills already on the resume are still reordered."
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
      </>
      ) : null}

      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}

      <Card className="p-5">
        <h3 className="text-base font-semibold text-foreground">Prepare a batch</h3>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          Paste a careers page, a list of job links, or several descriptions separated by a
          line of ---. Each opening gets its own email, and a resume whose summary and skills
          are tailored to that posting.
        </p>
        <form className="mt-4 flex flex-col gap-3" onSubmit={(event) => void handlePrepareBatch(event)}>
          <Field
            type="url"
            value={batchUrl}
            placeholder="https://jobs.example.com/careers"
            aria-label="Batch job link"
            onChange={(event) => setBatchUrl(event.target.value)}
          />
          <label className="block text-sm text-foreground">
            Links or descriptions
            <TextArea
              className="mt-1.5"
              rows={6}
              value={batchText}
              placeholder={"Senior Engineer at Acme\n...\n---\nDesigner at Nimbus\n..."}
              aria-label="Batch job text"
              onChange={(event) => setBatchText(event.target.value)}
            />
          </label>
          <Button
            type="submit"
            className="w-full sm:w-auto"
            disabled={
              busy !== null ||
              !status?.resume_saved ||
              (!batchUrl.trim() && batchText.trim().length < 40)
            }
          >
            {busy === "batch" ? "Preparing…" : "Prepare batch"}
          </Button>
        </form>
      </Card>

      {batch ? (
        <JobBatchPanel
          batch={batch}
          busy={busy === "batch-send"}
          approved={batchApproved}
          progress={batchProgress}
          result={batchResult}
          onChange={setBatch}
          onApproved={setBatchApproved}
          onSend={() => void handleSendBatch()}
        />
      ) : null}

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

            {draft.error ? (
              <p className="mt-2 text-sm text-destructive" role="alert">
                {draft.error}
              </p>
            ) : null}

            <JobDraftReview
              application={draft}
              locked={draft.status === "sent" || busy !== null}
              onChange={(patch) => {
                setApproved(false);
                setDraft({ ...draft, ...patch });
              }}
            />

            {pdfUrl ? (
              <details className="mt-4">
                <summary className="cursor-pointer text-sm text-foreground">Resume PDF</summary>
                <iframe
                  title={`Resume PDF for ${draft.company}`}
                  src={pdfUrl}
                  className="mt-3 h-80 w-full rounded-xl border border-border bg-background sm:h-[32rem]"
                />
              </details>
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
