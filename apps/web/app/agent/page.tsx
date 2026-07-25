import Link from "next/link";
import { ContextConversationPanel } from "@/app/context-conversation";
import {
  getFleetConversation,
  type ContextConversation,
  type FleetConversation,
} from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function GlobalAgentPage() {
  let unavailable = false;
  let fleet: FleetConversation = {
    session_id: null,
    available: false,
    unavailable_reason: "control_plane_unavailable",
    turns: [],
  };
  try {
    fleet = await getFleetConversation();
  } catch {
    unavailable = true;
  }
  const initial: ContextConversation = {
    scope_type: "fleet",
    target_id: "local",
    parent_agent_id: "local",
    title: "当前组织 Fleet",
    session_id: fleet.session_id,
    available: fleet.available,
    unavailable_reason: fleet.unavailable_reason,
    turns: fleet.turns,
  };
  return (
    <main>
      <Link className="back" href="/">
        ← 总览
      </Link>
      <section className="hero compact detail-head">
        <div className="eyebrow">M5.5 · GLOBAL · READ ONLY</div>
        <h1>Fleet 会话</h1>
        <p>
          当前组织的有界时间点汇总。服务端先筛选异常和有限来源，不会把整个 Fleet、全部日志或仓库正文交给 Provider。
        </p>
      </section>
      <ContextConversationPanel
        endpoint="/console/fleet/conversation/turns"
        initial={initial}
        unavailable={unavailable}
      />
    </main>
  );
}
