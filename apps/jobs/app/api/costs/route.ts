import { getWeeklyCosts } from "../../../lib/costs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    return Response.json(await getWeeklyCosts(), {
      headers: { "Cache-Control": "no-store, max-age=0" },
    });
  } catch (error) {
    console.error(error);
    return Response.json(
      {
        error:
          "Unable to read AWS costs. Check the server's Cost Explorer permission.",
      },
      { status: 502, headers: { "Cache-Control": "no-store, max-age=0" } },
    );
  }
}
