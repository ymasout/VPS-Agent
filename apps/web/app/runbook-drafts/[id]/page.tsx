import Link from "next/link";
import { ControlPlaneApiError, getRunbookDraft, type RunbookDraft } from "@/lib/api";
import { notFound } from "next/navigation";

export const dynamic = "force-dynamic";

export default async function RunbookDraftPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  let draft: RunbookDraft | null = null;
  try {
    draft = await getRunbookDraft(id);
  } catch (reason) {
    if (reason instanceof ControlPlaneApiError && reason.status === 404) notFound();
  }
  if (!draft) {
    return (
      <main>
        <Link className="back" href="/">← 总览</Link>
        <div className="empty error">Runbook 草稿暂时不可用。</div>
      </main>
    );
  }
  return (
    <main>
      <Link className="back" href={draft.source_event_id ? `/events/${draft.source_event_id}` : "/"}>
        ← 返回来源
      </Link>
      <section className="hero compact detail-head">
        <div className="eyebrow">M5.7 · DRAFT · NON-EXECUTABLE</div>
        <h1>{draft.title}</h1>
        <p>未审核、不可执行。该草稿不会创建、确认或执行 Operation。</p>
      </section>
      <section className="diagnostic">
        <h2>目标</h2>
        <p>{draft.content.objective ?? "—"}</p>
        <h3>展示步骤</h3>
        {(draft.content.display_steps ?? []).map((item, index) => <p key={index}>{index + 1}. {item}</p>)}
        <h3>前置检查</h3>
        {(draft.content.prerequisites ?? []).map((item, index) => <p key={index}>{item}</p>)}
        <p className="muted">风险：{draft.content.risk ?? "unknown"} · executable: false</p>
      </section>
      <section className="section">
        <div className="section-title"><h2>来源引用</h2><span>{draft.citations.length}</span></div>
        <div className="rows">
          {draft.citations.map((citation) =>
            citation.href && citation.available ? (
              <Link className="row" href={citation.href} key={citation.id}>
                <strong>{citation.source_type}</strong><span>{citation.source_label}</span><em>可用</em>
              </Link>
            ) : (
              <div className="row muted" key={citation.id}>
                <strong>墓碑</strong><span>{citation.source_label}</span><em>不可用</em>
              </div>
            ),
          )}
        </div>
      </section>
    </main>
  );
}
