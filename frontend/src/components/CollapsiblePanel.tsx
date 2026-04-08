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
        if ((e.target as HTMLElement).closest(".wr-ph")) {
          setCollapsed((c) => !c);
        }
      }}
    >
      {children}
    </div>
  );
}
