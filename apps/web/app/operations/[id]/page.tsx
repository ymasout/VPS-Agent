import Link from "next/link";
import React from "react";
import { ControlPlaneApiError, getOperation } from "@/lib/api";
import { getCurrentPrincipal, getPrincipalForwardHeaders } from "@/lib/principal";
import { StateView } from "@/app/ui/primitives";
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
      principal = await getCurrentPrincipal();
    }
  } catch (error) {
    const code = error instanceof ControlPlaneApiError ? error.status : 0;
    if (code === 404) notFound();
    return <main><Link className="back" href="/operations">← 操作列表</Link><StateView
      state={code === 401 || code === 403 ? "forbidden" : "error"}
      title={code === 401 || code === 403 ? "无权读取操作" : "操作详情暂时不可用"}
      description="请重新读取最新记录后核对。读取失败时不提供审批或回滚控件。"
    /></main>;
  }
  return (
    <main>
      <Link className="back" href="/operations">
        ← 操作列表
      </Link>
      <OperationPanel
        operation={operation}
        observedAt={new Date().toISOString()}
        namedAuthorization={namedAuthorization}
        canApprove={principal?.capabilities.includes("operation:approve") ?? false}
        canPlan={principal?.capabilities.includes("operation:plan") ?? false}
        currentPrincipalId={principal?.id ?? null}
      />
    </main>
  );
}
