import { isSameOrigin, validAgentName } from "../../../lib/registration";
import { NextRequest, NextResponse } from "next/server";

export async function POST(request: NextRequest) {
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  const protocol = request.headers.get("x-forwarded-proto") ?? request.nextUrl.protocol.replace(":", "");
  if (!isSameOrigin(request.headers.get("origin"), host, protocol)) {
    return NextResponse.json({ detail: "invalid request origin" }, { status: 403 });
  }

  const adminToken = process.env.ADMIN_API_TOKEN;
  if (!adminToken) {
    return NextResponse.json({ detail: "token generation is not configured" }, { status: 503 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "invalid request body" }, { status: 400 });
  }
  const name = typeof body === "object" && body !== null && "name" in body ? (body as { name: unknown }).name : null;
  if (!validAgentName(name)) {
    return NextResponse.json({ detail: "machine name must contain 1 to 255 characters" }, { status: 422 });
  }

  const apiURL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
  const response = await fetch(`${apiURL}/api/v1/registration-tokens`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-admin-token": adminToken },
    body: JSON.stringify({ name: name.trim(), expires_in_minutes: 30 }),
    cache: "no-store",
  });
  if (!response.ok) {
    return NextResponse.json({ detail: "control plane rejected the request" }, { status: response.status });
  }
  return NextResponse.json(await response.json(), { headers: { "cache-control": "no-store" } });
}
