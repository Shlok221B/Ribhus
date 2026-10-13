import { useEffect, useState } from "react";
import { api, type ISkillInfo } from "@/lib/api";
import { Badge, Button, Card, Field, PageHeader } from "@/components/ui";

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
      <PageHeader
        title="Skills"
        description="Installable playbooks for company research, travel, football, and more."
      />

      <Card className="flex flex-col gap-2 p-4 sm:flex-row sm:items-center">
        <Field
          value={source}
          onChange={(e) => setSource(e.target.value)}
          placeholder="Skill name or path (e.g. travel)"
          className="flex-1"
        />
        <Button
          disabled={busy || !source.trim()}
          onClick={() => void handleInstall()}
          className="w-full sm:w-auto"
        >
          Install
        </Button>
      </Card>

      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}

      <ul className="space-y-3">
        {skills.map((skill) => (
          <li key={skill.name + skill.path}>
            <Card className="flex flex-col gap-3 p-5 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-sm font-semibold text-foreground">
                    {skill.name}
                  </h3>
                  <Badge>{`v${skill.version}`}</Badge>
                  <Badge tone={skill.installed ? "success" : "info"}>
                    {skill.installed ? "installed" : "bundled"}
                  </Badge>
                </div>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                  {skill.description}
                </p>
                <p className="mt-2 truncate text-[11px] text-muted-foreground/70">
                  {skill.path}
                </p>
              </div>
              {skill.installed ? (
                <Button
                  variant="danger"
                  disabled={busy}
                  onClick={() => void handleRemove(skill.name)}
                  className="shrink-0 self-start"
                >
                  Remove
                </Button>
              ) : null}
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
};

export default SkillsPage;
