import type { TFileValue, TPayAction, TSectionSlot, TSignInDemo, TUploadField, TUserMenu, TUseSession } from "./plugin-types";

/** Story 22.7: the plugin slots of an app without those plugins (no auth, no uploads, no payments, no links): the
 *  generated `plugins.ts` names these instead, and they render nothing. */
const SIGNED_OUT = { enabled: false, ready: true, user: null };

export const useSession: TUseSession = () => SIGNED_OUT;
export const signInDemo: TSignInDemo = async () => false;
export const UserMenu: TUserMenu = () => null;
export const AppAuth: TSectionSlot = () => null;
export const UploadField: TUploadField = () => null;
export const FileValue: TFileValue = () => null;
export const PayAction: TPayAction = () => null;
export const AppPayment: TSectionSlot = () => null;
export const AppLinks: TSectionSlot = () => null;
