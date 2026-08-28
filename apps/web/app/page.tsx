import { ControlPlaneApiError, getConsoleOverview } from "@/lib/api";
import { getPrincipalForwardHeaders } from "@/lib/principal";
import { OverviewDashboard, OverviewError } from "./overview-dashboard";

export const dynamic = "force-dynamic";

export default async function Home() {
  try {
    const principalHeaders = await getPrincipalForwardHeaders();
    return <OverviewDashboard overview={await getConsoleOverview(principalHeaders ?? undefined)} />;
  } catch (error) {
    return <OverviewError forbidden={error instanceof ControlPlaneApiError && error.status === 403} />;
  }
}
