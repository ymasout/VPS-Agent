import { isSameOrigin } from "../../../../../../../../lib/registration";
import { NextRequest, NextResponse } from "next/server";

const identifier = /^[a-zA-Z0-9-]{1,64}$/;
const uuid =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; turnId: string }> },
) {
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  const protocol =
    request.headers.get("x-forwarded-proto") ?? request.nextUrl.protocol.replace(":", "");
  if (!isSameOrigin(request.headers.get("origin"), host, protocol)) {
    return NextResponse.json({ detail: "invalid request origin" }, { status: 403 });
  }
  const adminToken = process.env.ADMIN_API_TOKEN;
  if (!adminToken) {
    return NextResponse.json(
      { detail: "safe operation handoff is not configured" },
      { status: 503 },
    );
  }
  const { id, turnId } = await params;
  if (!identifier.test(id) || !identifier.test(turnId)) {
    return NextResponse.json({ detail: "invalid event or turn id" }, { status: 400 });
  }
  const rawBody = await request.text();
  if (new TextEncoder().encode(rawBody).length > 2048) {
    return NextResponse.json({ detail: "request body is too large" }, { status: 413 });
  }
  let payload: unknown;
  try {
    payload = JSON.parse(rawBody);
  } catch {
    return NextResponse.json({ detail: "invalid JSON body" }, { status: 400 });
  }
  if (
    !payload ||
    typeof payload !== "object" ||
    Array.isArray(payload) ||
    Object.keys(payload).some(
      (key) => !["client_request_id", "expires_in_seconds"].includes(key),
    )
  ) {
    return NextResponse.json({ detail: "invalid request body" }, { status: 422 });
  }
  const body = payload as Record<string, unknown>;
  if (
    typeof body.client_request_id !== "string" ||
    !uuid.test(body.client_request_id) ||
    typeof body.expires_in_seconds !== "number" ||
    !Number.isInteger(body.expires_in_seconds) ||
    body.expires_in_seconds < 60 ||
    body.expires_in_seconds > 900
  ) {
    return NextResponse.json({ detail: "invalid request body" }, { status: 422 });
  }
  const apiURL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
  let response: Response;
  try {
    response = await fetch(
      `${apiURL}/api/v1/events/${id}/conversation/turns/${turnId}/restart-plan`,
      {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-admin-token": adminToken,
        },
        body: JSON.stringify(body),
        cache: "no-store",
      },
    );
  } catch {
    return NextResponse.json(
      { detail: "control plane is unavailable" },
      { status: 502, headers: { "cache-control": "no-store" } },
    );
  }
  const result = await response
    .json()
    .catch(() => ({ detail: "control plane rejected the request" }));
  return NextResponse.json(result, {
    status: response.status,
    headers: { "cache-control": "no-store" },
  });
}
