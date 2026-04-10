import { useState } from "react";

interface Props {
  children: React.ReactNode;
  defaultCollapsed?: boolean;
}

export function CollapsiblePanel({ children, defaultCollapsed = false }: Props) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);

  return (
    <div
      className={`wr-collapse-wrap${collapsed ? " wr-collapsed" : ""}`}
      onClick={(e) => {
        const t = e.target as HTMLElement;
        if (!t.closest(".wr-ph")) return;
        // Don't swallow clicks that hit an interactive child of the header
        // (e.g. double-header match pills, future tab buttons). They have
        // their own onClick and the user isn't asking to collapse.
        if (t.closest("button, a, [role='button']")) return;
        setCollapsed((c) => !c);
      }}
    >
      {children}
    </div>
  );
}
