import * as React from "react";

import { cn } from "@/lib/utils";

type ButtonGroupProps = React.ComponentProps<"div"> & {
  orientation?: "horizontal" | "vertical";
};

function ButtonGroup({ className, orientation = "horizontal", ...props }: ButtonGroupProps) {
  return (
    <div
      role="group"
      data-orientation={orientation}
      className={cn(
        "inline-flex items-stretch gap-0",
        orientation === "vertical" ? "flex-col" : "flex-row",
        "[&>*:not(:first-child)]:rounded-l-none [&>*:not(:last-child)]:rounded-r-none",
        className
      )}
      {...props}
    />
  );
}

type ButtonGroupSeparatorProps = React.ComponentProps<"div"> & {
  orientation?: "horizontal" | "vertical";
};

function ButtonGroupSeparator({ className, orientation = "vertical", ...props }: ButtonGroupSeparatorProps) {
  return (
    <div
      aria-hidden="true"
      data-orientation={orientation}
      className={cn(
        "bg-slate-300",
        orientation === "vertical" ? "mx-0 h-auto w-px" : "my-0 h-px w-auto",
        className
      )}
      {...props}
    />
  );
}

function ButtonGroupText({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "inline-flex h-9 items-center whitespace-nowrap border border-slate-300 bg-slate-100 px-3 text-sm text-slate-600",
        className
      )}
      {...props}
    />
  );
}

export { ButtonGroup, ButtonGroupSeparator, ButtonGroupText };
