import { useEffect, useState } from "react";
import { api, type ISkillInfo } from "@/lib/api";

const SkillsPage = () => {
  const [skills, setSkills] = useState<ISkillInfo[]>([]);
  const [source, setSource] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      setSkills(await api.listSkills());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load skills");
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const handleInstall = async () => {
    const value = source.trim();
    if (!value || busy) return;
    setBusy(true);
    try {
      await api.installSkill(value);
      setSource("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Install failed");
    } finally {
      setBusy(false);
    }
  };

  const handleRemove = async (name: string) => {
    if (busy) return;
    setBusy(true);
    try {
      await api.removeSkill(name);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Remove failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <p className="text-sm text-muted-foreground">
        Installable skills for company research, travel, football, and more.
      </p>

      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          value={source}
          onChange={(e) => setSource(e.target.value)}
          placeholder="Skill name or path (e.g. travel)"
          className="flex-1 rounded border border-input bg-card px-3 py-2 text-sm"
        />
        <button
          type="button"
          disabled={busy || !source.trim()}
          onClick={() => void handleInstall()}
          className="rounded bg-primary px-4 py-2 font-mono text-xs uppercase text-primary-foreground disabled:opacity-40"
        >
          Install
        </button>
      </div>

      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}

      <ul className="space-y-2">
        {skills.map((skill) => (
          <li
            key={skill.name + skill.path}
            className="flex flex-col gap-2 rounded border border-border bg-card p-4 sm:flex-row sm:items-start sm:justify-between"
          >
            <div>
              <div className="font-mono text-sm text-foreground">
                {skill.name}{" "}
                <span className="text-muted-foreground">v{skill.version}</span>
              </div>
              <p className="mt-1 text-sm text-muted-foreground">{skill.description}</p>
              <p className="mt-1 font-mono text-[10px] text-muted-foreground/70">
                {skill.installed ? "installed" : "bundled/workspace"} ·{" "}
                {skill.path}
              </p>
            </div>
            {skill.installed ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => void handleRemove(skill.name)}
                className="shrink-0 rounded border border-destructive/40 px-3 py-1.5 font-mono text-[10px] uppercase text-destructive"
              >
                Remove
              </button>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
};

export default SkillsPage;
