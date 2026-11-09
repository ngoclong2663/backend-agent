"use client";

// A shell design plugin (Epic 30): the frame around every page, given the layout and the navigation this user may
// use (already filtered by role and area). Keep the brand, the area switch, the theme toggle and the user menu.
import { ThemeToggle } from "@/components/layout/ThemeToggle";
import { siteConfig } from "@/config/site";
import type { TShellProps } from "@/components/app/design-types";
import { UserMenu } from "@/components/app/plugins";
import { AreaSwitch, Brand, NavLinks } from "@/components/app/shells";

export function {{Name}}({ children, nav }: TShellProps) {
  return (
    <div className="flex min-h-svh flex-col" data-bga-shell="{{name}}">
      <header className="sticky top-0 z-20 border-b bg-background/90 backdrop-blur" data-bga-header>
        <div className="mx-auto flex h-14 w-full max-w-screen-2xl items-center gap-3 px-4">
          <Brand />
          <nav className="flex gap-1 overflow-x-auto" aria-label="Main">
            <NavLinks nav={nav} />
          </nav>
          <div className="ml-auto flex items-center gap-1">
            <AreaSwitch />
            {siteConfig.themeToggle && <ThemeToggle />}
            <UserMenu />
          </div>
        </div>
      </header>
      <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">{children}</main>
    </div>
  );
}
