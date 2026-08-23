import { useEffect, useState, type MouseEvent, type ReactNode } from "react";
import { artifactUrl, loadArtifactBlob } from "./api";
import { authEnabled } from "./auth";

function useArtifactObjectUrl(jobId: string, filename: string): string | null {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!authEnabled) return;
    let cancelled = false;
    void loadArtifactBlob(jobId, filename).then((blob) => {
      if (cancelled || !blob) return;
      setObjectUrl(URL.createObjectURL(blob));
    }).catch(() => undefined);
    return () => {
      cancelled = true;
      setObjectUrl((current) => {
        if (current) URL.revokeObjectURL(current);
        return null;
      });
    };
  }, [filename, jobId]);

  return objectUrl;
}

export function ArtifactLink({
  jobId,
  filename,
  children,
}: {
  jobId: string;
  filename: string;
  children: ReactNode;
}) {
  const [loading, setLoading] = useState(false);

  async function openArtifact(event: MouseEvent<HTMLAnchorElement>) {
    if (!authEnabled) return;
    event.preventDefault();
    if (loading) return;
    setLoading(true);
    const tab = window.open("", "_blank");
    try {
      const blob = await loadArtifactBlob(jobId, filename);
      if (!blob) {
        tab?.close();
        return;
      }
      const objectUrl = URL.createObjectURL(blob);
      if (tab) {
        tab.location.href = objectUrl;
      } else {
        window.open(objectUrl, "_blank", "noopener,noreferrer");
      }
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
    } catch {
      tab?.close();
    } finally {
      setLoading(false);
    }
  }

  return (
    <a
      href={authEnabled ? "#" : artifactUrl(jobId, filename)}
      target="_blank"
      rel="noreferrer"
      onClick={openArtifact}
      aria-busy={loading}
    >
      {loading ? "Opening…" : children}
    </a>
  );
}

export function ArtifactImage({
  jobId,
  filename,
  alt,
}: {
  jobId: string;
  filename: string;
  alt: string;
}) {
  const objectUrl = useArtifactObjectUrl(jobId, filename);
  const src = authEnabled ? objectUrl ?? undefined : artifactUrl(jobId, filename);
  return <img src={src} alt={alt} />;
}
