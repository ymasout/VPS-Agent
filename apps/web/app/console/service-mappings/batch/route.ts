import { NextRequest, NextResponse } from "next/server";

import { isSameOrigin } from "../../../../lib/registration";

export async function POST(request: NextRequest) {
  if (process.env.PRINCIPAL_WRITE_AUTHORIZATION_ENABLED === "true") {
    return NextResponse.json({ detail: "named service mappings must use the direct API route" }, { status: 409 });
  }
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  const protocol = request.headers.get("x-forwarded-proto") ?? request.nextUrl.protocol.replace(":", "");
  if (!isSameOrigin(request.headers.get("origin"), host, protocol)) {
    return NextResponse.json({ detail: "invalid request origin" }, { status: 403 });
  }
  const adminToken = process.env.ADMIN_API_TOKEN;
  if (!adminToken) {
    return NextResponse.json({ detail: "service mapping is not configured" }, { status: 503 });
  }
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "invalid request body" }, { status: 400 });
  }
  if (
    typeof body !== "object"
    || body === null
    || !Array.isArray((body as { items?: unknown }).items)
    || (body as { items: unknown[] }).items.length > 20
    || JSON.stringify(body).length > 65536
  ) {
    return NextResponse.json({ detail: "invalid request body" }, { status: 422 });
  }
  const apiURL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
  try {
    const response = await fetch(`${apiURL}/api/v1/service-mappings/batch`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-admin-token": adminToken },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const payload = await response.json().catch(() => ({ detail: "control plane rejected the request" }));
    return NextResponse.json(payload, {
      status: response.status,
      headers: { "cache-control": "no-store" },
    });
  } catch {
    return NextResponse.json({ detail: "control plane is unavailable" }, { status: 502 });
  }
}
