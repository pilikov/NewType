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
  if (!value) return "n/a";

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
  const hasCyrillic = scripts.some((script) => script.trim().toLowerCase().includes("cyrillic"));

  return (
    <Card className="overflow-hidden bg-white/90 backdrop-blur-sm">
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

      <CardHeader>
        <CardTitle className="text-xl">{release.name}</CardTitle>
        <CardDescription className="flex items-center gap-2">
          {displayEntityFavicon ? (
            <img
              src={displayEntityFavicon}
              alt={displayEntityName}
              className="h-4 w-4 rounded-sm"
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

      <CardContent className="space-y-1 text-sm text-slate-600">
        <p>Release date: {formatReleaseDate(release.release_date)}</p>
        <p>Authors: {release.authors.length ? release.authors.join(", ") : "—"}</p>
        <p>Scripts: {scripts.length ? scripts.join(", ") : "—"}</p>
        {hasCyrillic ? (
          <p>
            <span className="inline-flex rounded-full bg-slate-200 px-2 py-0.5 text-xs font-medium text-slate-700">
              Cyrillic
            </span>
          </p>
        ) : null}
      </CardContent>

      <CardFooter>
        {displayEntityUrl ? (
          <a
            href={displayEntityUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-md bg-[#F8F8F8] px-3 py-2 text-sm transition hover:bg-slate-100"
          >
            Open source <ExternalLink className="h-4 w-4" />
          </a>
        ) : null}
      </CardFooter>
    </Card>
  );
}
