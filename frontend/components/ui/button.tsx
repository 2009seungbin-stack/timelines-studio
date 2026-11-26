import * as React from "react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "outline";
type Size = "sm" | "md" | "icon";

const variants: Record<Variant, string> = {
  primary: "bg-accent text-white hover:bg-accent/85",
  secondary: "bg-panel2 text-fg hover:bg-line border border-line",
  outline: "border border-line2 text-fg hover:bg-panel2",
  ghost: "text-muted hover:text-fg hover:bg-panel2",
  danger: "bg-bad/90 text-white hover:bg-bad",
};
const sizes: Record<Size, string> = {
  sm: "h-7 px-2.5 text-xs gap-1.5",
  md: "h-9 px-3.5 text-sm gap-2",
  icon: "h-8 w-8 justify-center",
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "secondary", size = "md", type = "button", ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      className={cn(
        "inline-flex items-center rounded-md font-medium transition-colors select-none whitespace-nowrap",
        "disabled:opacity-45 disabled:pointer-events-none cursor-pointer",
        variants[variant], sizes[size], className,
      )}
      {...props}
    />
  ),
);
Button.displayName = "Button";
