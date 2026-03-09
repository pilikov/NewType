import { loadSourceMetaMap, sourceFaviconUiUrl } from "@/lib/source-meta";

export async function SourceLinks() {
  const sourceMap = await loadSourceMetaMap();
  const sources = Object.values(sourceMap).filter((source) => source.sourceId !== "catalog_snapshot");
  if (!sources.length) return null;

  return (
    <div className="flex items-center justify-end gap-3 text-sm text-slate-600">
      <span className="font-medium text-slate-700">Sources:</span>
      <div className="flex flex-wrap items-center gap-2">
        {sources.map((source) => {
          const href = source.baseUrl || "#";
          const faviconUrl = sourceFaviconUiUrl(source);
          const label = source.name || source.sourceId;

          return (
            <a
              key={source.sourceId}
              href={href}
              target="_blank"
              rel="noreferrer"
              className="inline-flex h-8 w-8 items-center justify-center rounded-md bg-[#F8F8F8]"
              title={label}
              aria-label={label}
            >
              {faviconUrl ? (
                <img src={faviconUrl} alt={label} className="h-4 w-4" loading="lazy" />
              ) : (
                <span className="text-xs font-semibold text-slate-500">{label.slice(0, 1).toUpperCase()}</span>
              )}
            </a>
          );
        })}
      </div>
    </div>
  );
}
