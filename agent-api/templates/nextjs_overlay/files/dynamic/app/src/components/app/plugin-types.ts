import type { QueryClient } from "@tanstack/react-query";
import type { TAppAction, TAppEntity, TAppSection, TRecord, TSession } from "./app";
import type { TFieldProps } from "./form/types";

/** Story 22.7: what the kit's plugin slots take (`plugins.ts` names the plugins' components, else `plugin-stubs.tsx`).
 *  A plugin's frontend files (`templates/plugins/<name>/frontend/files/`) implement these. */
export type TSectionSlot = (props: { section: TAppSection; title: string }) => React.ReactNode;
export type TUseSession = () => TSession;
/** Story 28.5: sign in as a demo account (false without demo accounts or when the sign-in failed). */
export type TSignInDemo = (login: string, queryClient: QueryClient) => Promise<boolean>;
export type TUserMenu = () => React.ReactNode;
export type TUploadField = (props: TFieldProps) => React.ReactNode;
export type TFileValue = (props: { entity: TAppEntity | undefined; field: string; record: TRecord; compact?: boolean }) => React.ReactNode;
export type TPayAction = (props: { action: TAppAction; record: TRecord | undefined; variant?: TAppAction["variant"] }) => React.ReactNode;
