"use client";

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import {
  COST_CATEGORY_LABELS,
  COST_CATEGORY_ORDER,
  type DailyCost,
  type WeeklyCostPayload,
} from "../../lib/cost-types.ts";
import styles from "./cost-viewer.module.css";

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const dayLabel = new Intl.DateTimeFormat("en-US", {
  weekday: "short",
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});

const refreshTime = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  timeZone: "UTC",
});

function formatDay(date: string) {
  return dayLabel.format(new Date(`${date}T00:00:00Z`));
}

function formatServiceAmount(value: number) {
  if (value > 0 && value < 0.01) return "<$0.01";
  return money.format(value);
}

function displayServices(day: DailyCost) {
  const visible = day.services.filter((service) => service.amount >= 0.005);
  const remainder = day.services
    .filter((service) => service.amount < 0.005)
    .reduce((sum, service) => sum + service.amount, 0);
  return remainder > 0
    ? [...visible, { name: "metered-other", label: "Other metered usage", amount: remainder }]
    : visible;
}

export function CostViewer({
  initialPayload = null,
  initialError = null,
}: {
  initialPayload?: WeeklyCostPayload | null;
  initialError?: string | null;
}) {
  const [payload, setPayload] = useState<WeeklyCostPayload | null>(initialPayload);
  const [error, setError] = useState<string | null>(initialError);
  const [refreshing, setRefreshing] = useState(false);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const response = await fetch("/api/costs", { cache: "no-store" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "Unable to load AWS costs.");
      setPayload(body);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load AWS costs.");
    } finally {
      setRefreshing(false);
    }
  }, []);

  const maxDailyTotal = useMemo(
    () => Math.max(0, ...(payload?.days.map((day) => day.total) || [])),
    [payload],
  );

  return (
    <main className={styles.shell}>
      <header className={styles.topbar}>
        <Link className={styles.brand} href="/" aria-label="Diana Compute run monitor">
          <span className={styles.brandMark} aria-hidden="true">D</span>
          <span>
            <small>Diana Compute</small>
            <strong>Cost monitor</strong>
          </span>
        </Link>
        <nav className={styles.navigation} aria-label="Diana Compute views">
          <Link href="/">Jobs</Link>
          <span aria-current="page">Costs</span>
        </nav>
        <button
          className={styles.refreshButton}
          type="button"
          onClick={() => void refresh()}
          disabled={refreshing}
        >
          <span aria-hidden="true">↻</span>
          {refreshing ? "Refreshing" : "Refresh costs"}
        </button>
      </header>

      <div className={styles.content}>
        <div className={styles.heading}>
          <div>
            <p className={styles.eyebrow}>AWS Cost Explorer · unblended USD</p>
            <h1>Seven-day cost breakdown</h1>
          </div>
          {payload && (
            <div className={styles.freshness}>
              <span className={styles.liveDot} aria-hidden="true" />
              Updated {refreshTime.format(new Date(payload.generatedAt))} UTC
            </div>
          )}
        </div>

        {error && (
          <div className={styles.error} role="alert">
            <strong>Cost data unavailable</strong>
            <span>{error}</span>
            <button type="button" onClick={() => void refresh()}>Try again</button>
          </div>
        )}

        {!payload && !error && (
          <div className={styles.loading} aria-live="polite">
            <span aria-hidden="true" />
            Reading the latest completed billing days…
          </div>
        )}

        {payload && (
          <>
            <section className={styles.summary} aria-label="Seven-day cost summary">
              <div><span>Seven-day cost</span><strong>{money.format(payload.total)}</strong><small>{formatDay(payload.start)}–{formatDay(payload.days.at(-1)?.date || payload.start)}</small></div>
              <div><span>Daily average</span><strong>{money.format(payload.dailyAverage)}</strong><small>Across {payload.days.length} completed days</small></div>
              <div><span>Peak day</span><strong>{money.format(payload.peakDay?.total || 0)}</strong><small>{payload.peakDay ? formatDay(payload.peakDay.date) : "No usage"}</small></div>
            </section>

            <div className={styles.legend} aria-label="Cost category legend">
              {COST_CATEGORY_ORDER.map((key, index) => (
                <span key={key}><i className={styles[`series${index + 1}`]} />{COST_CATEGORY_LABELS[key]}</span>
              ))}
            </div>

            <section
              className={styles.chart}
              role="img"
              aria-label="Daily AWS costs on a shared scale, with exact service costs listed under each stacked bar."
              data-testid="daily-cost-chart"
            >
              {payload.days.map((day) => {
                const totalWidth = maxDailyTotal ? (day.total / maxDailyTotal) * 100 : 0;
                return (
                  <article className={styles.day} key={day.date}>
                    <div className={styles.dayHeading}>
                      <time dateTime={day.date}>{formatDay(day.date)}</time>
                      <strong>{money.format(day.total)}</strong>
                    </div>
                    <div className={styles.scale} aria-hidden="true">
                      <div className={styles.bar} style={{ width: `${totalWidth}%` }}>
                        {COST_CATEGORY_ORDER.map((key, index) => {
                          const categoryWidth = day.total
                            ? (day.categories[key] / day.total) * 100
                            : 0;
                          return categoryWidth > 0 ? (
                            <span
                              className={styles[`series${index + 1}`]}
                              key={key}
                              style={{ width: `${categoryWidth}%` }}
                            />
                          ) : null;
                        })}
                      </div>
                    </div>
                    <dl className={styles.details}>
                      {displayServices(day).map((service) => (
                        <div key={service.name}>
                          <dt>{service.label}</dt>
                          <dd>{formatServiceAmount(service.amount)}</dd>
                        </div>
                      ))}
                    </dl>
                  </article>
                );
              })}
            </section>

            <p className={styles.note}>
              Shared scale: $0–{money.format(maxDailyTotal)} per day. Cost Explorer marks these figures as {payload.estimated ? "estimated" : "final"}; AWS may revise recent billing data.
            </p>
          </>
        )}
      </div>
    </main>
  );
}
