"use client";

import { ExternalLink } from "lucide-react";
import { useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle
} from "@/components/ui/card";

export type ReleaseItem = {
  release_id: string;
  source_id: string;
  source_name: string;
  source_url: string | null;
  source_favicon_url?: string | null;
  studio_id?: string | null;
  studio_name?: string | null;
  studio_url?: string | null;
  studio_favicon_url?: string | null;
  name: string;
  release_date: string | null;
  authors: string[];
  scripts?: string[];
  image_url: string | null;
  raw?: {
    release_kind?: string;
    is_new_version?: boolean;
    version?: string | null;
  };
};

type ReleaseCardProps = {
  release: ReleaseItem;
};

function extractScripts(release: ReleaseItem): string[] {
  const primary = release.scripts;
  if (Array.isArray(primary)) return primary.map((v) => String(v));

  const rawScripts = (release.raw as { scripts?: unknown } | undefined)?.scripts;
  if (Array.isArray(rawScripts)) return rawScripts.map((v) => String(v));
  if (typeof rawScripts === "string") return rawScripts.split(",").map((v) => v.trim()).filter(Boolean);

  return [];
}

function hasRemoteImage(url: string | null): boolean {
  if (!url) return false;
  return url.startsWith("http://") || url.startsWith("https://") || url.startsWith("/");
}

function formatReleaseDate(value: string | null): string {
  if (!value) return "—";

  const normalized = /^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00Z` : value;
  const dt = new Date(normalized);
  if (Number.isNaN(dt.getTime())) return value;

  return new Intl.DateTimeFormat("en-US", {
    day: "numeric",
    month: "long",
    year: "numeric"
  }).format(dt);
}

export function ReleaseCard({ release }: ReleaseCardProps) {
  const scripts = extractScripts(release);
  const [imgError, setImgError] = useState(false);
  const hasImage = hasRemoteImage(release.image_url) && !imgError;
  const displayEntityName = release.studio_name || release.source_name;
  const displayEntityFavicon = release.studio_favicon_url || release.source_favicon_url || null;
  const displayEntityUrl = release.studio_url || release.source_url;
  const releaseKind = release.raw?.release_kind;
  const isNewVersion = release.raw?.is_new_version || releaseKind === "new_version";
  const isFutureFonts = release.source_id === "futurefonts";
  const badgeLabel = isFutureFonts
    ? isNewVersion
      ? `New Version${release.raw?.version ? ` v${release.raw.version}` : ""}`
      : releaseKind === "new_release"
        ? "New Release"
        : null
    : null;

  return (
    <Card className="overflow-hidden rounded-[var(--radius)] bg-white/90 pt-0 pb-6 backdrop-blur-sm">
      {hasImage ? (
        <img
          src={release.image_url ?? undefined}
          alt={release.name}
          loading="lazy"
          className="h-44 w-full object-cover"
          onError={() => setImgError(true)}
        />
      ) : (
        <div className="h-44 w-full bg-gradient-to-br from-slate-200 to-slate-100" />
      )}

      <CardHeader className="px-6 pt-6">
        <CardTitle className="text-[1.125rem] font-semibold leading-tight">{release.name}</CardTitle>
        <CardDescription className="flex flex-wrap items-center gap-2 text-base">
          {displayEntityFavicon ? (
            <img
              src={displayEntityFavicon}
              alt={displayEntityName}
              className="h-4 w-4 shrink-0 rounded-sm"
              loading="lazy"
            />
          ) : null}
          <span>{displayEntityName}</span>
          {badgeLabel ? (
            <span
              className={
                isNewVersion
                  ? "rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800"
                  : "rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800"
              }
            >
              {badgeLabel}
            </span>
          ) : null}
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-1 px-6 text-base text-slate-600">
        <p>{formatReleaseDate(release.release_date)}</p>
        <p>{release.authors.length ? release.authors.join(", ") : "—"}</p>
        <p>{scripts.length ? scripts.join(", ") : "—"}</p>
      </CardContent>

      <CardFooter className="px-6 pb-6">
        {displayEntityUrl ? (
          <a
            href={displayEntityUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex min-h-11 items-center gap-2 rounded-[var(--radius)] bg-[#E9F1FA] px-5 py-2.5 text-base font-medium text-slate-800 transition hover:bg-[#dce8f4]"
          >
            Open source <ExternalLink className="h-5 w-5" />
          </a>
        ) : null}
      </CardFooter>
    </Card>
  );
}
