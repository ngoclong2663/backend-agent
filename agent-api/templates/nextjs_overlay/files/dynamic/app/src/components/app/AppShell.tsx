"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { ThemeToggle } from "@/components/layout/ThemeToggle";
import { siteConfig } from "@/config/site";
import { app } from "./app";
import { designRegistry } from "./design-registry";
import { icons } from "./icons";
import { useLayout } from "./layout";
import { ListeningBar, UserMenu } from "./plugins";
import { AreaSwitch, BOTTOM_TABS_MAX, SidebarShell, active, useNav } from "./shells";
import { slots } from "./slots";
import { TourMount } from "./tour/TourMount";

type AppShellProps = {
  children: ReactNode;
};

/** The app's shell (Epic 23): the layout's shell plugin (Epic 30: `design-registry.ts` holds the ones this app uses)
 *  over the same navigation, filtered by role and by the current area. */
export function AppShell({ children }: AppShellProps) {
  const design = useLayout();
  const nav = useNav();
  const bottom = design.mobileNav === "bottom-tabs" && nav.length <= BOTTOM_TABS_MAX && nav.length > 1;
  return (
    <>
      <ShellLayout>{children}</ShellLayout>
      {app.media?.audio && <ListeningBar bottomTabs={bottom} />}
      <TourMount />
    </>
  );
}

function ShellLayout({ children }: AppShellProps) {
  const design = useLayout();
  const nav = useNav();
  const pathname = usePathname() ?? "/";
  if (slots.shell) {
    // Story 23.11: an engine-written shell, given the same navigation and account controls
    const Shell = slots.shell;
    const items = nav.map((item) => {
      const Icon = icons[item.icon];
      return { label: item.label, href: item.href, icon: Icon ? <Icon className="size-4" aria-hidden /> : null, current: active(pathname, item.href) };
    });
    return (
      <Shell appName={app.name} nav={items} account={<><AreaSwitch />{siteConfig.themeToggle && <ThemeToggle />}<UserMenu /></>}>
        {children}
      </Shell>
    );
  }
  const Layout = designRegistry.shells[design.shell] ?? SidebarShell;
  return (
    <Layout design={design} nav={nav}>
      {children}
    </Layout>
  );
}
