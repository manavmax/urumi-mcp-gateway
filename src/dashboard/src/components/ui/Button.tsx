import * as React from "react";
type Props = React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger"; size?: "sm" | "md" };
export function Button({ variant = "primary", size = "md", className = "", ...props }: Props) {
  const v = variant === "primary" ? "" : variant;
  const s = size === "sm" ? "small" : "";
  return <button className={[v, s, className].filter(Boolean).join(" ")} {...props} />;
}
