import { isSameOrigin } from "../../../../../lib/registration";
import { NextRequest, NextResponse } from "next/server";

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  const protocol = request.headers.get("x-forwarded-proto") ?? request.nextUrl.protocol.replace(":", "");
  if (!isSameOrigin(request.headers.get("origin"), host, protocol)) {
    return NextResponse.json({ detail: "invalid request origin" }, { status: 403 });
  }
  const adminToken = process.env.ADMIN_API_TOKEN;
  if (!adminToken) return NextResponse.json({ detail: "diagnostics are not configured" }, { status: 503 });
  const { id } = await params;
  if (!/^[a-zA-Z0-9-]{1,64}$/.test(id)) return NextResponse.json({ detail: "invalid event id" }, { status: 400 });
  const apiURL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
  let response: Response;
  try {
    response = await fetch(`${apiURL}/api/v1/events/${id}/diagnostics`, {
      method: "POST",
      headers: { "x-admin-token": adminToken },
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ detail: "control plane is unavailable" }, { status: 502 });
  }
  const payload = await response.json().catch(() => ({ detail: "control plane rejected the request" }));
  return NextResponse.json(payload, { status: response.status, headers: { "cache-control": "no-store" } });
}
