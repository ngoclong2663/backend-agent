"use client";

import { canUse, type TAppSection } from "./app";
import { AppActions } from "./AppActions";
import { AppDashboard } from "./AppDashboard";
import { AppDetail } from "./AppDetail";
import { AppForm } from "./AppForm";
import { AppList } from "./AppList";
import { AppAuth, AppLinks, AppPayment, useSession } from "./plugins";
import { AppChart } from "./features/AppChart";
import { AppPresence } from "./features/AppPresence";
import { AppResume } from "./features/AppResume";
import { AppTimeline } from "./features/AppTimeline";
import { CommentThread } from "./features/CommentThread";

type AppSectionProps = {
  pageId: string;
  section: TAppSection;
  title: string;
  /** The first list of a page is its heading (h1); a tab's or a dashboard's list is a sub-heading. */
  heading: "h1" | "h2";
  /** In a set of tabs the tab names the list; its heading stays for screen readers. */
  hideTitle?: boolean;
};

/** An app section by its component name; the markers let checks find it on the page. */
export function AppSection({ pageId, section, title, heading, hideTitle }: AppSectionProps) {
  const session = useSession();
  // Story 22.7: a section on an operation this user may not call is left out (a member sees no "all bookings")
  if (session.enabled && section.data?.operationId && !canUse(section.data.operationId, session)) return null;
  let body = null;
  switch (section.component) {
    case "AppList":
      body = <AppList section={section} heading={heading} pageId={pageId} hideTitle={hideTitle} />;
      break;
    case "AppDetail":
      body = <AppDetail section={section} />;
      break;
    case "AppForm":
      body = <AppForm section={section} title={title} />;
      break;
    case "AppDashboard":
      body = <AppDashboard section={section} />;
      break;
    case "AppActions":
      body = <AppActions section={section} />;
      break;
    case "AppAuth":
      body = <AppAuth section={section} title={title} />;
      break;
    case "AppLinks":
      body = <AppLinks section={section} title={title} />;
      break;
    case "AppPayment":
      body = <AppPayment section={section} title={title} />;
      break;
    case "CommentThread": // Epic 33: the comments feature
      body = <CommentThread section={section} />;
      break;
    case "AppResume": // Epic 33: the enrollment feature's resume card
      body = <AppResume section={section} />;
      break;
    case "AppPresence": // Epic 33: the availability feature's Online switch
      body = <AppPresence section={section} />;
      break;
    case "AppTimeline": // Epic 33: the tracking feature
      body = <AppTimeline section={section} />;
      break;
    case "AppChart": // Epic 33: the telemetry feature
      body = <AppChart section={section} />;
      break;
  }
  return (
    <section data-bga-section={`${pageId}/${section.id}`} data-bga-component={section.component} className="min-w-0">
      {body}
    </section>
  );
}
