import { Fragment } from "react";
import type { Metadata } from "next";
import Link from "next/link";

import { api, type HealthReport, type JobHealth } from "@/lib/api";
import { describeSchedule, formatMoment } from "@/lib/format";

export const metadata: Metadata = {
  title: "Data health",
  description:
    "Whether the jobs that load this system have run, when each one last ran, and how " +
    "many rows it wrote. Reported by the system about itself.",
};

/** The windows offered. A `days` parameter outside this list is ignored, not trusted. */
const WINDOWS = [1, 7, 30] as const;

/**
 * Level to pill. DESIGN.md §3: status is green / violet / red, never blue, and the word
 * is always beside the colour - so each of these carries its own label.
 *
 * `never_ran` is deliberately the neutral pill rather than the red one. Red is
 * `--broken`, and a job that has not run is not broken: on this machine the scheduler
 * is simply not running, so most of the list is in that state. Painting sixty rows red
 * would say "sixty things have failed", which is not what the report says. The word
 * beside the pill still says exactly what the level is.
 */
const LEVELS: Record<JobHealth["level"], { pill: string; word: string }> = {
  ok: { pill: "pill ok", word: "ran ok" },
  warning: { pill: "pill attention", word: "needs attention" },
  error: { pill: "pill broken", word: "failed" },
  never_ran: { pill: "pill neutral", word: "never ran" },
};

function Level({ level }: { level: JobHealth["level"] }) {
  const shown = LEVELS[level];
  return <span className={shown.pill}>{shown.word}</span>;
}

/** The headline four, straight from the report. Nothing here is counted by this page. */
function Tally({ report }: { report: HealthReport }) {
  const cells: Array<{ count: number; level: JobHealth["level"] }> = [
    { count: report.ok, level: "ok" },
    { count: report.warning, level: "warning" },
    { count: report.error, level: "error" },
    { count: report.never_ran, level: "never_ran" },
  ];

  return (
    <div className="grid cols-4">
      {cells.map((cell) => (
        <div className="card" key={cell.level}>
          <div className="stat-value">{cell.count}</div>
          <div className="stat-name">
            <Level level={cell.level} />
          </div>
        </div>
      ))}
    </div>
  );
}

export default async function DataHealthPage({
  searchParams,
}: {
  searchParams: Promise<{ days?: string }>;
}) {
  const { days } = await searchParams;
  // String comparison, not parsing: a value that is not one of the offered windows
  // falls back to the default rather than reaching the API.
  const windowDays = WINDOWS.find((candidate) => String(candidate) === days) ?? 7;

  let report: HealthReport;

  try {
    report = await api.health(windowDays);
  } catch (error) {
    const detail = error instanceof Error ? error.message : "unknown error";
    return (
      <>
        <h1>Data health</h1>
        <div className="notice bad">
          <h3>The health report could not be loaded</h3>
          <p>
            This page asks the API whether its own loading jobs have been running, and
            that request did not come back. So the honest answer to &ldquo;is the data
            fresh?&rdquo; right now is: unknown. Not fine, and not broken — unknown.
          </p>
          <p>
            Reported as: <span className="num">{detail}</span>
          </p>
          <p>
            Running this locally, the API is the uvicorn process on port 8000. Reload
            once it is answering.
          </p>
        </div>
      </>
    );
  }

  const hasRun = report.jobs.filter((job) => job.level !== "never_ran");
  const neverRan = report.jobs.filter((job) => job.level === "never_ran");
  const checkedAt = formatMoment(report.checked_at);

  return (
    <>
      <h1>Data health</h1>
      <p className="lede">
        Every figure on this site was put there by a job that ran at a particular time.
        This page is those jobs reporting on themselves: which ones ran, when each last
        ran, and how many rows it wrote.
      </p>

      <nav aria-label="Reporting window">
        <p className="muted">Looking at the last:</p>
        <p>
          {WINDOWS.map((candidate) => (
            <Fragment key={candidate}>
              <Link
                href={`/data-health?days=${candidate}`}
                className={candidate === windowDays ? "button" : "button quiet"}
                aria-current={candidate === windowDays ? "page" : undefined}
              >
                {candidate === 1 ? "24 hours" : `${candidate} days`}
              </Link>{" "}
            </Fragment>
          ))}
        </p>
      </nav>

      {report.error > 0 ? (
        <div className="notice bad">
          <h3>Jobs reported errors in this window</h3>
          <p>
            One or more jobs ran and came back with a failure. Each is listed in the
            table below with what it reported. Figures those jobs load may be older than
            their usual publication date says they should be.
          </p>
        </div>
      ) : report.needs_a_human ? (
        <div className="notice">
          <h3>This report is flagged for a human, and here is what it is flagging</h3>
          <p>
            No job failed in this window. What the flag has picked up is that most of the
            jobs listed here have not run at all — the scheduler that would trigger them
            is not running on this machine, so jobs that are defined have simply never
            been started.
          </p>
          <p>
            On a machine with the scheduler running, that would mean something had gone
            wrong. Here it means the scheduler is off. The jobs that <i>are</i> running
            are being triggered another way, and they report normally in the table below.
          </p>
        </div>
      ) : (
        <div className="notice">
          <h3>Nothing is flagged in this window</h3>
          <p>
            Every job the system expected to run has run, and none of them reported a
            problem. The table below shows when each one last ran.
          </p>
        </div>
      )}

      <h2>The tally</h2>
      <Tally report={report} />

      <div className="explain">
        <span className="tag">What a job is, and what the four words mean</span>
        <p>
          A job is one scheduled fetch: one company&rsquo;s filings from SEC EDGAR, one
          series from FRED, one news feed. Each is meant to run at a fixed time and write
          rows into the database. This page asks one question of each — did it run inside
          the window, and what came back.
        </p>
        <p>
          <b>Ran ok</b> — it ran and reported success. <b>Needs attention</b> — it ran,
          or was due to, and something about the result was not what the job expected.{" "}
          <b>Failed</b> — it ran and returned an error. <b>Never ran</b> — it did not run
          in this window at all, which on this machine usually means the scheduler that
          triggers it is not running.
        </p>
        <p>
          A job that ran and wrote <b>0 rows</b> is not a failure and not a blank. It
          means the job went and looked and there was nothing new to store — which is a
          finding, and a different thing from never having looked.
        </p>
      </div>

      <h2>Jobs that ran</h2>
      {hasRun.length === 0 ? (
        <div className="notice">
          <h3>No job ran inside this window</h3>
          <p>
            Every job in the report is in the never-ran state for this window. Try a
            longer window above, or start the scheduler. Nothing here has failed — the
            system has simply not been asked to fetch anything.
          </p>
        </div>
      ) : (
        <>
          <div className="scroller">
            <table>
              <caption>
                Jobs with something to report in the{" "}
                {windowDays === 1 ? "24 hours" : `${windowDays} days`} before{" "}
                {checkedAt}. Times are UTC.
              </caption>
              <thead>
                <tr>
                  <th scope="col">Job</th>
                  <th scope="col">Scheduled</th>
                  <th scope="col">Last ran</th>
                  <th scope="col" className="num">
                    Runs
                  </th>
                  <th scope="col" className="num">
                    Rows written
                  </th>
                  <th scope="col">Status</th>
                  <th scope="col">What it reported</th>
                </tr>
              </thead>
              <tbody>
                {hasRun.map((job) => (
                  <tr key={job.name}>
                    <th scope="row">{job.name}</th>
                    <td>{describeSchedule(job.scheduled_at_utc)}</td>
                    <td>
                      {formatMoment(job.last_run_at) ?? (
                        <span className="muted">no run recorded</span>
                      )}
                    </td>
                    <td className="num">{job.runs_in_window}</td>
                    <td className="num">{job.rows_in_window}</td>
                    <td>
                      <Level level={job.level} />
                    </td>
                    <td className="wrap-cell">
                      {job.finding ?? <span className="faint">nothing to report</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {/* Conditional on purpose. A flat "this table scrolls" is only true while the
              columns happen to overflow, and column widths changed twice on this page
              alone. `.scroll-hint` hides above an 860px *viewport*, which is not the
              same question as whether the *container* overflows - inside `details.more`
              the container stops growing at --prose (~551px) and the two diverge. This
              wording asserts nothing about the current width, so it cannot go stale. */}
          <p className="scroll-hint">
            If this table is wider than your screen, it scrolls sideways rather than the
            page.
          </p>
        </>
      )}

      {neverRan.length > 0 && (
        <details className="more">
          <summary>
            The {report.never_ran} jobs that did not run in this window, and when each is
            due
          </summary>
          <p>
            These are defined and have a time set. Nothing triggered them, because the
            scheduler is not running here. They are folded away because they all say the
            same thing, not because they are hidden — the tally above counts every one.
          </p>
          <ul>
            {neverRan.map((job) => (
              <li key={job.name}>
                {job.name} <span className="faint">— {describeSchedule(job.scheduled_at_utc)}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      <details className="more">
        <summary>How to read a schedule like &ldquo;hourly, at 15 past&rdquo;</summary>
        <p>
          The system stores a schedule in one of three ways, and this page writes all
          three out in words. A fixed time means the job runs once a day at that hour.
          Hourly means it runs every hour, at those minutes past — so a news feed set to
          15 past runs at 00:15, 01:15, 02:15 and so on. No fixed time means nothing runs
          it automatically; a person does, by hand.
        </p>
        <p>Every time on this page is UTC, including the last-ran column.</p>
      </details>

      <div className="source">
        <dl>
          <dt>Reported at</dt>
          <dd>{checkedAt}</dd>
          <dt>Window</dt>
          <dd>
            the {report.window_days === 1 ? "24 hours" : `${report.window_days} days`}{" "}
            before that moment
          </dd>
          <dt>Source</dt>
          <dd>
            this system&rsquo;s own run log. It is the system reporting on itself, not an
            outside check of it.
          </dd>
        </dl>
      </div>
    </>
  );
}
