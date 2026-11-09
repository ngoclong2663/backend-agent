// Epic 30 (Story 30.2): the props contracts every design plugin of a kind implements (decision D2). The generated
// `design-registry.ts` maps the plugin names an app uses to components of these types; the kit's AppShell, AppList,
// AppDetail and the grid views dispatch through it and never name a plugin themselves.
import type { ReactNode } from "react";
import type { TAppAction, TAppEntity, TAppNavItem, TAppSection, TDesign, TEntityDesign, TFieldRoles, TRecord } from "./app";

/** A shell: the app's frame around a page, given the layout and the navigation this user may use. */
export type TShellProps = { children: ReactNode; design: TDesign; nav: TAppNavItem[] };

/** A list view: the same AppList section (operation, parameters, row actions, `allowedActions`), another presentation. */
export type TViewProps = { section: TAppSection; entity?: TAppEntity; records: TRecord[]; design: TEntityDesign };

/** A home that replaces the main list's rendering on the home page (a catalogue, a featured record): the list's
 *  props plus the route of the whole list for "See all". */
export type THomeProps = TViewProps & { listHref?: string };

/** A detail view: one record, its title, the fields to show (the display field removed), and its action buttons. */
export type TDetailProps = {
  section: TAppSection;
  entity?: TAppEntity;
  record: TRecord;
  design: TEntityDesign;
  fields: string[];
  title: string;
  actions: ReactNode;
};

/** A card: one record in a grid view (Story 30.4). `boxed`: inside a bordered card (the `cards` view) rather than
 *  free-standing under its media (the `media-grid` view); `size`: how much room the grid gives it. */
export type TCardProps = {
  entity?: TAppEntity;
  record: TRecord;
  roles: TFieldRoles;
  design: TEntityDesign;
  title: string;
  href?: string;
  actions: TAppAction[];
  boxed?: boolean;
  size?: "sm" | "md" | "lg";
};
