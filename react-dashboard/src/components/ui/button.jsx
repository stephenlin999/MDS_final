import * as React from "react";
import { cva } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex h-11 items-center justify-center gap-2 whitespace-nowrap rounded-xl px-4 text-sm font-medium transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 active:scale-[0.98]",
  {
    variants: {
      variant: {
        default:
          "bg-gradient-to-r from-[#0052FF] to-[#4D7CFF] text-white shadow-sm hover:-translate-y-0.5 hover:shadow-accent hover:brightness-110",
        secondary:
          "border border-border bg-white text-foreground hover:-translate-y-0.5 hover:border-blue-200 hover:bg-muted hover:shadow-sm",
        ghost: "text-muted-foreground hover:bg-muted hover:text-foreground",
        danger: "bg-[#C0392B] text-white hover:-translate-y-0.5 hover:brightness-110",
      },
      size: {
        default: "h-11 px-4",
        sm: "h-9 rounded-lg px-3",
        lg: "h-12 px-6",
        icon: "h-11 w-11 p-0",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

const Button = React.forwardRef(({ className, variant, size, ...props }, ref) => (
  <button ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />
));
Button.displayName = "Button";

export { Button, buttonVariants };
