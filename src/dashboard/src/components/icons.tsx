/* Inline SVG icon set: 1.75px line icons, currentColor, no icon library.
   Logo A is the final mark: rounded square, arch (doorway), horizontal line
   through the arch opening. All icons are decorative; text labels carry meaning. */
import * as React from "react";

export type IconName =
  | "logo" | "grid" | "server" | "users" | "user" | "key" | "shield" | "chat"
  | "search" | "logout" | "chevron" | "plus" | "check" | "check-circle" | "x"
  | "x-circle" | "clock" | "wrench" | "alert" | "pause" | "arrow-up" | "arrow-right"
  | "send" | "cart" | "doc" | "globe" | "edit" | "trash" | "copy" | "eye" | "history"
  | "bell" | "dot" | "deny" | "download" | "filter" | "lock";

const PATHS: Record<Exclude<IconName, "logo">, React.ReactNode> = {
  grid: (
    <>
      <rect x="3.5" y="3.5" width="7" height="7" rx="2" />
      <rect x="13.5" y="3.5" width="7" height="7" rx="2" />
      <rect x="3.5" y="13.5" width="7" height="7" rx="2" />
      <rect x="13.5" y="13.5" width="7" height="7" rx="2" />
    </>
  ),
  server: (
    <>
      <rect x="3" y="4" width="18" height="7" rx="2" />
      <rect x="3" y="13" width="18" height="7" rx="2" />
      <path d="M7 7.5h.01M7 16.5h.01" />
    </>
  ),
  users: (
    <>
      <circle cx="9" cy="8" r="3.2" />
      <path d="M3.5 19c.6-3 2.8-4.6 5.5-4.6s4.9 1.6 5.5 4.6" />
      <circle cx="17" cy="9" r="2.4" />
      <path d="M16 14.3c2.3.2 3.9 1.6 4.4 4" />
    </>
  ),
  user: (
    <>
      <circle cx="12" cy="8" r="3.5" />
      <path d="M5.5 19.5c.8-3.4 3.3-5 6.5-5s6 1.6 6.5 5" />
    </>
  ),
  key: (
    <>
      <circle cx="8" cy="14" r="4" />
      <path d="M11 11L20 2M16 6l3 3" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3l7 2.6v5.1c0 4.4-2.9 8.3-7 10.3-4.1-2-7-5.9-7-10.3V5.6L12 3z" />
      <path d="M9 11.6l2.1 2.1 4-4.2" />
    </>
  ),
  chat: <path d="M20 12.5a7.5 7.5 0 0 1-7.5 7.5c-1.3 0-2.6-.3-3.7-.9L4 20l1-4.6A7.5 7.5 0 1 1 20 12.5z" />,
  search: (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M15.8 15.8L20 20" />
    </>
  ),
  logout: (
    <>
      <path d="M15 4.5H7a2.5 2.5 0 0 0-2.5 2.5v10A2.5 2.5 0 0 0 7 19.5h8" />
      <path d="M12 12h9M17.5 8.5L21 12l-3.5 3.5" />
    </>
  ),
  chevron: <path d="M8 10l4 4 4-4" />,
  check: <path d="M4.5 12.5l5 5 10-11" />,
  "check-circle": (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M8.5 12.3l2.4 2.4 4.6-4.9" />
    </>
  ),
  x: <path d="M6 6l12 12M18 6L6 18" />,
  "x-circle": (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M9.2 9.2l5.6 5.6M14.8 9.2l-5.6 5.6" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </>
  ),
  wrench: <path d="M14.5 6.5a4 4 0 1 0 4.2 6.3L21 10l-7 7-1.8-1.8a4 4 0 0 1-6.3 4.2 4 4 0 0 1 5.3-5.9" />,
  alert: (
    <>
      <path d="M12 4.5L21 19.5H3L12 4.5z" />
      <path d="M12 10v4.5M12 17h.01" />
    </>
  ),
  pause: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M9.5 9v6M14.5 9v6" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  "arrow-up": <path d="M12 19V5M6 11l6-6 6 6" />,
  "arrow-right": <path d="M4 12h15M13 6l6 6-6 6" />,
  send: (
    <>
      <path d="M4 11.5L20 4l-4.5 16-3.7-6.5L4 11.5z" />
      <path d="M11.8 13.5L20 4" />
    </>
  ),
  cart: (
    <>
      <path d="M4 5h2.2l2 10.5A2 2 0 0 0 10.1 17h7.4a2 2 0 0 0 2-1.6L21 8H7" />
      <circle cx="10.5" cy="20" r="1.4" />
      <circle cx="18" cy="20" r="1.4" />
    </>
  ),
  doc: (
    <>
      <path d="M6 3.5h8L19 8.5V20.5H6z" />
      <path d="M13.5 3.5v5.5H19M9 13h6M9 16.5h6" />
    </>
  ),
  globe: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M3.5 12h17M12 3.5c2.5 2.3 3.8 5.3 3.8 8.5s-1.3 6-3.8 8.5c-2.5-2.3-3.8-5-3.8-8.5s1.3-6 3.8-8.5z" />
    </>
  ),
  trash: (
    <>
      <path d="M4.5 7h15M9.5 7V5.5A1.5 1.5 0 0 1 11 4h2a1.5 1.5 0 0 1 1.5 1.5V7M7 7l1 12.5A1.5 1.5 0 0 0 9.5 21h5a1.5 1.5 0 0 0 1.5-1.5L17 7" />
    </>
  ),
  eye: (
    <>
      <path d="M2.5 12S6 5.8 12 5.8 21.5 12 21.5 12 18 18.2 12 18.2 2.5 12 2.5 12z" />
      <circle cx="12" cy="12" r="2.8" />
    </>
  ),
  copy: (
    <>
      <rect x="9" y="9" width="11" height="11" rx="2.5" />
      <path d="M5 15H6.5M5 11V5.5A1.5 1.5 0 0 1 6.5 3.5H15" />
    </>
  ),
  edit: (
    <>
      <path d="M4 20h4L19 9l-4-4L4 16v4z" />
      <path d="M14.5 5.5l4 4" />
    </>
  ),
  history: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </>
  ),
  bell: (
    <>
      <path d="M6 9.5a6 6 0 0 1 12 0c0 4 1.5 5.5 1.5 5.5h-15S6 13.5 6 9.5z" />
      <path d="M10 19a2.2 2.2 0 0 0 4 0" />
    </>
  ),
  dot: <circle cx="12" cy="12" r="4.5" fill="currentColor" stroke="none" />,
  deny: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M6 6l12 12" />
    </>
  ),
  download: (
    <>
      <path d="M12 4v11M7.5 10.5L12 15l4.5-4.5" />
      <path d="M4.5 19.5h15" />
    </>
  ),
  filter: <path d="M4 6.5h16M7 12h10M10 17.5h4" />,
  lock: (
    <>
      <rect x="5" y="10.5" width="14" height="9.5" rx="2.5" />
      <path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" />
    </>
  ),
};

/* 1.75px line icon per the mockups; the .ic / .ic.sm CSS classes (styles.css,
   ported from design/mockups) carry size, stroke and colour. */
export function Icon({ name, size = 18, sm, className, style }: { name: IconName; size?: number; sm?: boolean; className?: string; style?: React.CSSProperties }) {
  if (name === "logo") return <LogoMark size={size} className={className} style={style} />;
  return (
    <svg
      className={["ic", sm ? "sm" : "", className].filter(Boolean).join(" ")}
      style={style}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name as keyof typeof PATHS]}
    </svg>
  );
}

/* Logo A (final): rounded square, arch, horizontal line through the arch opening. */
export function LogoMark({ size = 24, className, style }: { size?: number; className?: string; style?: React.CSSProperties }) {
  return (
    <svg
      className={className}
      style={style}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      aria-hidden="true"
      focusable="false"
    >
      <rect x="3" y="3" width="18" height="18" rx="5.5" />
      <path d="M9.2 16.8v-3.4a2.8 2.8 0 0 1 5.6 0v3.4" />
      <path d="M7 12h10" />
    </svg>
  );
}
