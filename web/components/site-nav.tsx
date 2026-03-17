"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function SiteNav() {
  const pathname = usePathname();
  const isReleases = pathname === "/";
  const isNews = pathname === "/news";

  return (
    <nav className="flex w-full justify-center border-b border-slate-200 bg-slate-50/80 py-3">
      <div className="flex gap-6">
        <Link
          href="/"
          className={`text-sm font-medium transition-colors ${
            isReleases ? "text-slate-900" : "text-slate-500 hover:text-slate-800"
          }`}
        >
          Releases
        </Link>
        <Link
          href="/news"
          className={`text-sm font-medium transition-colors ${
            isNews ? "text-slate-900" : "text-slate-500 hover:text-slate-800"
          }`}
        >
          News
        </Link>
      </div>
    </nav>
  );
}
