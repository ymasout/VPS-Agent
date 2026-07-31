import Link from "next/link";
import { getOperation, getPrincipal } from "@/lib/api";
import { getPrincipalForwardHeaders } from "@/lib/principal";
import { notFound } from "next/navigation";
import { OperationPanel } from "./operation-panel";

export const dynamic = "force-dynamic";

export default async function OperationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const namedAuthorization = process.env.PRINCIPAL_WRITE_AUTHORIZATION_ENABLED === "true";
  let operation;
  let principal = null;
  try {
    const principalHeaders = await getPrincipalForwardHeaders();
    operation = await getOperation(id, principalHeaders ?? undefined);
    if (namedAuthorization && principalHeaders) {
      principal = await getPrincipal(principalHeaders);
    }
  } catch {
    notFound();
  }
  return (
    <main>
      <Link className="back" href={operation.source_event_id ? `/events/${operation.source_event_id}` : "/"}>
        ← 返回
      </Link>
      <OperationPanel
        operation={operation}
        namedAuthorization={namedAuthorization}
        canApprove={principal?.capabilities.includes("operation:approve") ?? false}
        currentPrincipalId={principal?.id ?? null}
      />
    </main>
  );
}
