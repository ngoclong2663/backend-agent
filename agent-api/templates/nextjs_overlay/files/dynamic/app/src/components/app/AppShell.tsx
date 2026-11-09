"use client";

import { Search } from "lucide-react";
import type { ReactNode } from "react";
import { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ThemeToggle } from "@/components/layout/ThemeToggle";
import { Input } from "@/components/ui/input";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { siteConfig } from "@/config/site";
import { cn } from "@/lib/utils";
import { app, canUse, pageOperation, type TAppNavItem, type TDesign } from "./app";
import { AppBreadcrumbs } from "./AppBreadcrumbs";
import { icons } from "./icons";
import { useLayout } from "./layout";
import { slots } from "./slots";
import { TourMount } from "./tour/TourMount";
import { ListeningBar, UserMenu, useSession } from "./plugins";
import { inSentence, t } from "./messages";

type AppShellProps = {
  children: ReactNode;
};

const BOTTOM_TABS_MAX = 5;

function active(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

/** The navigation this user may use (Story 22.7: items the role cannot use are hidden) in the current area. */
function useNav(): TAppNavItem[] {
  const session = useSession();
  const layout = useLayout();
  const pages = Object.fromEntries(Object.entries(app.pages).map(([id, page]) => [page.route, id]));
  const prefix = layout.area && layout.area.prefix !== "/" ? layout.area.prefix : null;
  const others = (app.areas ?? []).filter((area) => area.prefix !== "/" && area !== layout.area).map((area) => area.prefix);
  return app.nav.filter((item) => {
    if (!canUse(pageOperation(pages[item.href] ?? ""), session)) return false;
    if (prefix) return item.href === prefix || item.href.startsWith(`${prefix}/`);
    return !others.some((other) => item.href === other || item.href.startsWith(`${other}/`));
  });
}

/** The main entity's list page and its search parameter (`<section>.q`, as AppList reads it), for a top bar's search. */
function mainSearch(design: TDesign): { route: string; param: string } | null {
  for (const page of Object.values(app.pages)) {
    if (page.route.includes("[")) continue;
    const section = page.sections.find(
      (s) => s.component === "AppList" && s.content?.entity === design.mainEntity && !s.content?.tab && s.content?.variant !== "recent",
    );
    if (section?.content?.controls?.search) return { route: page.route, param: `${section.id}.q` };
  }
  return null;
}

/** Story 23.10: the other areas this user may open (a manager can view the app as a learner does). */
function AreaSwitch() {
  const session = useSession();
  const layout = useLayout();
  const role = session.user?.role ? String(session.user.role) : null;
  const areas = (app.areas ?? []).filter(
    (area) => area !== layout.area && (area.prefix === "/" || (role !== null && area.roles.includes(role))),
  );
  if (!role || areas.length === 0) return null;
  return (
    <nav className="hidden items-center gap-1 text-sm sm:flex" aria-label={t("viewAs")} data-bga-areas>
      <span className="text-muted-foreground">{t("viewAs")}:</span>
      {areas.map((area) => (
        <Link key={area.id} href={area.prefix} className="rounded-md px-2 py-1 font-medium hover:bg-accent">
          {area.label}
        </Link>
      ))}
    </nav>
  );
}

function Brand({ compact = false }: { compact?: boolean }) {
  const AppIcon = icons[app.icon];
  return (
    <Link href="/" className="flex shrink-0 items-center gap-2 font-semibold" data-bga-brand>
      <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
        {AppIcon && <AppIcon className="size-4" aria-hidden />}
      </span>
      {!compact && <span className="hidden truncate sm:inline">{app.name}</span>}
    </Link>
  );
}

function NavLinks({ nav, className }: { nav: TAppNavItem[]; className?: string }) {
  const pathname = usePathname() ?? "/";
  return nav.map((item) => {
    const Icon = icons[item.icon];
    const current = active(pathname, item.href);
    return (
      <Link
        key={item.href}
        href={item.href}
        aria-current={current ? "page" : undefined}
        className={cn(
          "flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium whitespace-nowrap text-muted-foreground transition-colors hover:bg-accent hover:text-foreground aria-[current=page]:bg-accent aria-[current=page]:text-foreground",
          className,
        )}
      >
        {Icon && <Icon className="size-4" aria-hidden />}
        {item.label}
      </Link>
    );
  });
}

/** Phones (Epic 23): up to five sections as tabs at the bottom, in thumb reach. */
function BottomTabs({ nav }: { nav: TAppNavItem[] }) {
  const pathname = usePathname() ?? "/";
  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-30 flex border-t bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
      aria-label={t("sections")}
      data-bga-bottom-tabs
    >
      {nav.map((item) => {
        const Icon = icons[item.icon];
        const current = active(pathname, item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={current ? "page" : undefined}
            className="flex min-w-0 flex-1 flex-col items-center gap-0.5 py-2 text-xs text-muted-foreground aria-[current=page]:font-semibold aria-[current=page]:text-foreground"
          >
            {Icon && <Icon className="size-5" aria-hidden />}
            <span className="max-w-full truncate px-1">{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

function TopSearch({ design }: { design: TDesign }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const target = mainSearch(design);
  if (!target) return null;
  const plural = inSentence(app.entities[design.mainEntity ?? ""]?.plural ?? t("records"));
  return (
    <form
      role="search"
      className="relative mx-auto hidden w-full max-w-xl flex-1 sm:block"
      onSubmit={(event) => {
        event.preventDefault();
        const query_ = query.trim();
        router.push(query_ ? `${target.route}?${encodeURIComponent(target.param)}=${encodeURIComponent(query_)}` : target.route);
      }}
    >
      <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
      <Input
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={t("search", { name: plural })}
        aria-label={t("search", { name: plural })}
        className="h-10 rounded-full pl-9"
      />
    </form>
  );
}

/** A top bar (catalogues, feeds, storefronts): the brand, the sections in the bar (or as tabs under it), a search
 *  over the main entity and the account; on phones the sections move to bottom tabs or a scrolling row. */
function TopBarShell({ children, design, nav }: { children: ReactNode; design: TDesign; nav: TAppNavItem[] }) {
  const tabs = design.shell === "topbar-tabs";
  const bottom = design.mobileNav === "bottom-tabs" && nav.length <= BOTTOM_TABS_MAX && nav.length > 1;
  return (
    <div className="flex min-h-svh flex-col" data-bga-shell={design.shell}>
      <header className="sticky top-0 z-20 border-b bg-background/90 backdrop-blur" data-bga-header>
        <div className="mx-auto flex h-16 w-full max-w-screen-2xl items-center gap-4 px-4 sm:px-6">
          <Brand />
          {!tabs && (
            <nav className="hidden items-center gap-1 lg:flex" aria-label="Main">
              <NavLinks nav={nav} />
            </nav>
          )}
          <TopSearch design={design} />
          <div className="ml-auto flex items-center gap-1">
            <AreaSwitch />
            {siteConfig.themeToggle && <ThemeToggle />}
            <UserMenu />
          </div>
        </div>
        {(tabs || !bottom) && nav.length > 0 && (
          <nav
            className={cn("mx-auto flex w-full max-w-screen-2xl gap-1 overflow-x-auto px-4 pb-2 sm:px-6", !tabs && "lg:hidden", tabs && bottom && "max-md:hidden")}
            aria-label={t("sections")}
          >
            <NavLinks nav={nav} />
          </nav>
        )}
      </header>
      <main className={cn("flex-1 px-4 py-6 sm:px-6 lg:px-8", bottom && "pb-24 md:pb-6")}>{children}</main>
      {bottom && <BottomTabs nav={nav} />}
    </div>
  );
}

/** A sidebar (back offices, workspaces), or a rail of icons: the sections in a collapsible sidebar (a sheet on
 *  phones, or bottom tabs), a top bar with the page's place and the theme switch. */
function SidebarShell({ children, design, nav }: { children: ReactNode; design: TDesign; nav: TAppNavItem[] }) {
  const pathname = usePathname() ?? "/";
  const bottom = design.mobileNav === "bottom-tabs" && nav.length <= BOTTOM_TABS_MAX && nav.length > 1;
  return (
    <SidebarProvider defaultOpen={design.shell !== "rail"}>
      <Sidebar collapsible="icon" data-bga-shell={design.shell}>
        <SidebarHeader>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton size="lg" render={<Link href="/" />}>
                <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
                  {(() => {
                    const AppIcon = icons[app.icon];
                    return AppIcon ? <AppIcon className="size-4" aria-hidden /> : null;
                  })()}
                </span>
                <span className="flex min-w-0 flex-col leading-tight">
                  <span className="truncate font-semibold">{app.name}</span>
                  {app.tagline && <span className="truncate text-xs text-muted-foreground">{app.tagline}</span>}
                </span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupContent>
              <SidebarMenu>
                {nav.map((item) => {
                  const Icon = icons[item.icon];
                  return (
                    <SidebarMenuItem key={item.href}>
                      <SidebarMenuButton
                        isActive={active(pathname, item.href)}
                        tooltip={item.label}
                        render={<Link href={item.href} />}
                      >
                        {Icon && <Icon aria-hidden />}
                        <span>{item.label}</span>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  );
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <SidebarRail />
      </Sidebar>
      <SidebarInset className="min-w-0">
        <header className="sticky top-0 z-10 flex h-14 shrink-0 items-center gap-2 border-b bg-background/95 px-4 backdrop-blur" data-bga-header>
          <SidebarTrigger className={cn("-ml-1", bottom && "max-md:hidden")} />
          {bottom && (
            <span className="md:hidden">
              <Brand compact />
            </span>
          )}
          <AppBreadcrumbs />
          <div className="ml-auto flex items-center gap-1">
            <AreaSwitch />
            {siteConfig.themeToggle && <ThemeToggle />}
            <UserMenu />
          </div>
        </header>
        <div className={cn("flex-1 px-4 py-6 sm:px-6 lg:px-8", bottom && "pb-24 md:pb-6")}>{children}</div>
        {bottom && <BottomTabs nav={nav} />}
      </SidebarInset>
    </SidebarProvider>
  );
}

/** The app's shell (Epic 23): the layout's shell (sidebar, rail, top bar, top bar with tabs) over the same
 *  navigation, filtered by role and by the current area. */
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
  if (design.shell === "topbar" || design.shell === "topbar-tabs") {
    return (
      <TopBarShell design={design} nav={nav}>
        {children}
      </TopBarShell>
    );
  }
  return (
    <SidebarShell design={design} nav={nav}>
      {children}
    </SidebarShell>
  );
}
