import Link from "next/link";
import { getOperation } from "@/lib/api";
import { notFound } from "next/navigation";
import { OperationPanel } from "./operation-panel";

export const dynamic = "force-dynamic";

export default async function OperationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let operation;
  try { operation = await getOperation(id); } catch { notFound(); }
  return <main><Link className="back" href={operation.source_event_id ? `/events/${operation.source_event_id}` : "/"}>← 返回</Link><OperationPanel operation={operation} /></main>;
}
