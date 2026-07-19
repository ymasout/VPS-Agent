import { isSameOrigin } from "../../../../lib/registration";
import { NextRequest, NextResponse } from "next/server";

export async function POST(request: NextRequest) {
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  const protocol = request.headers.get("x-forwarded-proto") ?? request.nextUrl.protocol.replace(":", "");
  if (!isSameOrigin(request.headers.get("origin"), host, protocol)) {
    return NextResponse.json({ detail: "invalid request origin" }, { status: 403 });
  }
  const adminToken = process.env.ADMIN_API_TOKEN;
  if (!adminToken) return NextResponse.json({ detail: "GitHub synchronization is not configured" }, { status: 503 });
  const apiURL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
  try {
    const response = await fetch(`${apiURL}/api/v1/github/sync`, {
      method: "POST",
      headers: { "x-admin-token": adminToken },
      cache: "no-store",
    });
    const payload = await response.json().catch(() => ({ detail: "control plane rejected the request" }));
    return NextResponse.json(payload, { status: response.status, headers: { "cache-control": "no-store" } });
  } catch {
    return NextResponse.json({ detail: "control plane is unavailable" }, { status: 502 });
  }
}
