import type { Metadata } from "next";
import { getWeeklyCosts } from "../../lib/costs";
import { CostViewer } from "./cost-viewer";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Diana Compute — AWS costs",
  description: "Live seven-day AWS cost breakdown for Diana compute.",
};

export default async function CostsPage() {
  let initialPayload = null;
  let initialError = null;
  try {
    initialPayload = await getWeeklyCosts();
  } catch (error) {
    console.error(error);
    initialError =
      "Unable to read AWS costs. Check the server's Cost Explorer permission.";
  }
  return <CostViewer initialPayload={initialPayload} initialError={initialError} />;
}
