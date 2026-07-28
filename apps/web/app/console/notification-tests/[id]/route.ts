import { isSameOrigin } from "../../../../lib/registration";
import { NextRequest, NextResponse } from "next/server";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function GET(request: NextRequest, context: { params: Promise<{ id: string }> }) {
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  const protocol = request.headers.get("x-forwarded-proto") ?? request.nextUrl.protocol.replace(":", "");
  if (!isSameOrigin(request.headers.get("origin"), host, protocol)) {
    return NextResponse.json({ detail: "invalid request origin" }, { status: 403 });
  }
  const { id } = await context.params;
  if (!UUID.test(id)) return NextResponse.json({ detail: "invalid request id" }, { status: 400 });
  const adminToken = process.env.ADMIN_API_TOKEN;
  if (!adminToken) return NextResponse.json({ detail: "notification tests are not configured" }, { status: 503 });
  const apiURL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
  try {
    const response = await fetch(`${apiURL}/api/v1/notification-tests/${encodeURIComponent(id)}`, {
      headers: { "x-admin-token": adminToken },
      cache: "no-store",
    });
    return NextResponse.json(await response.json(), {
      status: response.status,
      headers: { "cache-control": "no-store" },
    });
  } catch {
    return NextResponse.json({ detail: "control plane is unavailable" }, { status: 502 });
  }
}
