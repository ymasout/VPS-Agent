import Link from "next/link";
import { notFound } from "next/navigation";
import { ContextConversationPanel } from "@/app/context-conversation";
import {
  ContextConversation,
  ControlPlaneApiError,
  getServiceConversation,
} from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ServiceConversationPage({
  params,
}: {
  params: Promise<{ id: string; instanceId: string }>;
}) {
  const { id, instanceId } = await params;
  let conversation: ContextConversation | null = null;
  let unavailable = false;
  try {
    conversation = await getServiceConversation(instanceId);
  } catch (error) {
    if (error instanceof ControlPlaneApiError && error.status === 404) notFound();
    unavailable = true;
  }
  if (conversation && conversation.parent_agent_id !== id) notFound();
  const view =
    conversation ??
    ({
      scope_type: "service",
      target_id: instanceId,
      parent_agent_id: id,
      title: "服务",
      session_id: null,
      available: false,
      unavailable_reason: "control_plane_unavailable",
      turns: [],
    } satisfies ContextConversation);
  return (
    <main>
      <Link className="back" href={`/servers/${id}`}>← 返回机器详情</Link>
      <section className="hero compact detail-head">
        <div className="status online"><span /> read only</div>
        <h1>{view.title}</h1>
        <p>单服务上下文 · 仅使用控制平面已有记录</p>
      </section>
      <ContextConversationPanel
        endpoint={`/console/service-instances/${instanceId}/conversation/turns`}
        initial={view}
        unavailable={unavailable}
      />
    </main>
  );
}
