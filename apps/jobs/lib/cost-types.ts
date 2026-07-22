export const COST_CATEGORY_ORDER = [
  "s3",
  "ec2Compute",
  "ec2Other",
  "costExplorer",
  "networkSecurity",
  "other",
] as const;

export type CostCategoryKey = (typeof COST_CATEGORY_ORDER)[number];

export const COST_CATEGORY_LABELS: Record<CostCategoryKey, string> = {
  s3: "S3",
  ec2Compute: "EC2 compute",
  ec2Other: "EC2 other",
  costExplorer: "Cost Explorer",
  networkSecurity: "KMS + VPC",
  other: "Other",
};

export type DailyServiceCost = {
  name: string;
  label: string;
  amount: number;
};

export type DailyCost = {
  date: string;
  total: number;
  estimated: boolean;
  categories: Record<CostCategoryKey, number>;
  services: DailyServiceCost[];
};

export type WeeklyCostPayload = {
  generatedAt: string;
  start: string;
  end: string;
  currency: "USD";
  estimated: boolean;
  total: number;
  dailyAverage: number;
  peakDay: { date: string; total: number } | null;
  days: DailyCost[];
};
