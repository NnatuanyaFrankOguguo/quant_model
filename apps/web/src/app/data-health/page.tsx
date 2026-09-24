import type { Metadata } from "next";
import Link from "next/link";

import {
  ApiError,
  ApiTimeout,
  api,
  failTheBuildInstead,
  type HealthReport,
  type JobHealth,
} from "@/lib/api";
import { SERVICE_IS_SLOW, count, describeSchedule, formatMoment } from "@/lib/format";
import { Disclose } from "@/components/disclose";

export const metadata: Metadata = {
  title: "Data health",
  description:
    "Whether the jobs that load this system have run, when each one last ran, and how " +
    "many rows it wrote. Reported by the system about itself.",
};

/** The windows offered. A `days` parameter outside this list is ignored, not trusted. */
const WINDOWS = [1, 7, 30] as const;

const windowInWords = (days: number) => (days === 1 ? "24 hours" : `${days} days`);

/**
 * Level to pill. DESIGN.md §5: status is green / violet / red, never blue, and the word
 * is always beside the colour - so each of these carries its own label.
 *
 * `never_ran` is deliberately the grey pill rather than the red one. Red is `--broken`,
 * and a job that has not run is not broken: on this machine the scheduler is simply not
 * running, so most of the list is in that state. Painting fifty-six rows red would say
 * "fifty-six things have failed", which is not what the report says.
 */
const LEVELS: Record<JobHealth["level"], { pill: string; word: string }> = {
  ok: { pill: "pill ok", word: "ran ok" },
  warning: { pill: "pill attention", word: "needs attention" },
  error: { pill: "pill broken", word: "failed" },
  never_ran: { pill: "pill never_ran", word: "never ran" },
};

function Level({ level }: { level: JobHealth["level"] }) {
  const shown = LEVELS[level];
  return <span className={shown.pill}>{shown.word}</span>;
}

/**
 * A moment, or the fact that there was not one.
 *
 * `.absent` has to land on the cell - `globals.css` styles `td.absent` - so this returns
 * the `<td>`. The phrase is neither of `lib/format`'s two absences on purpose: a job with
 * no last-run time is not a figure we have failed to fetch and not a line a publisher
 * left out. Nothing ran, and that is a third kind of absence.
 */
function LastRunCell({ iso }: { iso: string | null }) {
  const written = formatMoment(iso);
  return written ? <td>{written}</td> : <td className="absent">no run recorded</td>;
}

export default async function DataHealthPage({
  searchParams,
}: {
  searchParams: Promise<{ days?: string }>;
}) {
  const { days } = await searchParams;
  // String comparison, not parsing: a value that is not one of the offered windows falls
  // back to the default rather than reaching the API.
  const windowDays = WINDOWS.find((candidate) => String(candidate) === days) ?? 7;

  let report: HealthReport;

  try {
    report = await api.health(windowDays);
  } catch (error) {
    // This route reads `searchParams`, so it is dynamic and is not prerendered today -
    // but the rule in DESIGN.md §8 is unconditional, and a page that later stops reading
    // them becomes statically bakeable the moment the guard is missing.
    failTheBuildInstead(error);

    // See the note on /macro: slow is not broken, and must not be dressed as broken.
    const slow = error instanceof ApiTimeout;
    return (
      <>
        <h1>Data health</h1>
        {/* The title is a bold lead rather than an `<h3>`: this notice follows the
            `<h1>` directly, and DESIGN.md §9 allows no skipped heading level. */}
        <div className={slow ? "notice" : "notice bad"}>
          <p>
            <b>
              {slow
                ? "This is taking longer than the page waits."
                : "The health report could not be loaded."}
            </b>{" "}
            {slow
              ? SERVICE_IS_SLOW
              : "This page asks the API whether its own loading jobs have been running, " +
                "and that request did not come back. So the honest answer to “is the " +
                "data fresh?” right now is: unknown. Not fine, and not broken — unknown."}
          </p>
          <p>
            Reported as:{" "}
            <span className="num">
              {error instanceof ApiError
                ? `${error.status} from ${error.path}`
                : error instanceof Error
                  ? error.message
                  : "unknown error"}
            </span>
          </p>
          <p>
            Running this locally, the API is the uvicorn process on port 8000. Reload once
            it is answering.
          </p>
        </div>
      </>
    );
  }

  // Selection, not arithmetic: the four counts printed above come from the report itself,
  // never from the length of either of these lists.
  const reported = report.jobs.filter((job) => job.level !== "never_ran");
  const neverRan = report.jobs.filter((job) => job.level === "never_ran");
  const checkedAt = formatMoment(report.checked_at);

  const tally: Array<{ figure: number; level: JobHealth["level"] }> = [
    { figure: report.ok, level: "ok" },
    { figure: report.warning, level: "warning" },
    { figure: report.error, level: "error" },
    { figure: report.never_ran, level: "never_ran" },
  ];

  return (
    <>
      <h1>Data health</h1>
      <p className="page-note">
        Every figure on this site was put there by a job that ran at a particular time.
        This is those jobs reporting on themselves.
      </p>

      <nav className="tabs" aria-label="Reporting window">
        {WINDOWS.map((candidate) => (
          <Link
            key={candidate}
            href={`/data-health?days=${candidate}`}
            aria-current={candidate === windowDays ? "page" : undefined}
          >
            Last {windowInWords(candidate)}
          </Link>
        ))}
      </nav>

      <div className="metrics">
        {tally.map((cell) => (
          <div className="metric" key={cell.level}>
            <div className="metric-name">
              <Level level={cell.level} />
            </div>
            <div className="metric-value num">{count(cell.figure)}</div>
          </div>
        ))}
      </div>

      {report.error > 0 ? (
        <div className="notice bad">
          <p>
            <b>Jobs reported errors in this window.</b> Each is in the table below with
            what it reported. Figures those jobs load may be older than their usual
            publication date suggests.
          </p>
        </div>
      ) : report.needs_a_human ? (
        <div className="notice">
          <p>
            <b>Flagged for a human, and this is what it is flagging.</b> No job failed in
            this window. What the flag has picked up is that most of the jobs listed here
            have not run at all.
          </p>
        </div>
      ) : (
        <div className="notice">
          <p>
            <b>Nothing is flagged in this window.</b> Every job the system expected to run
            has run, and none of them reported a problem. The table below shows when each
            one last ran.
          </p>
        </div>
      )}

      <div className="panel">
        <div className="panel-head">
          <h2>Jobs with something to report</h2>
        </div>
        {reported.length === 0 ? (
          <div className="panel-body">
            <p className="muted">
              No job ran or was flagged inside this window. Try a longer window above.
              Nothing here has failed — the system has simply not been asked to fetch
              anything.
            </p>
          </div>
        ) : (
          <>
            <div className="scroller">
              <table>
                <caption>
                  Jobs that ran, or were expected to, in the {windowInWords(windowDays)}{" "}
                  before {checkedAt}. Times are UTC.
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Job</th>
                    <th scope="col">Scheduled</th>
                    <th scope="col">Last run</th>
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
                  {reported.map((job) => (
                    <tr key={job.name}>
                      <th scope="row">{job.name}</th>
                      <td>{describeSchedule(job.scheduled_at_utc)}</td>
                      <LastRunCell iso={job.last_run_at} />
                      <td className="num">{count(job.runs_in_window)}</td>
                      <td className="num">{count(job.rows_in_window)}</td>
                      <td>
                        <Level level={job.level} />
                      </td>
                      <td className="wrap-cell">
                        {job.finding ?? (
                          <span className="faint">nothing to report</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {/* Conditional on purpose. A flat "this table scrolls" is only true while the
                columns happen to overflow, and column widths changed twice on this page
                alone. `.scroll-hint` hides above a 900px *viewport*, which is not the
                same question as whether the *container* overflows. This wording asserts
                nothing about the current width, so it cannot go stale. */}
            <p className="scroll-hint">
              If this table is wider than your screen, it scrolls sideways rather than the
              page.
            </p>
          </>
        )}
      </div>

      {neverRan.length > 0 ? (
        <div className="panel">
          <div className="panel-head">
            <h2>Jobs that did not run in this window</h2>
          </div>
          <div className="scroller">
            <table>
              <caption>
                Each of these is defined and has a time set. Nothing triggered them. There
                is no last-run column because not one of them has a last run — an empty
                column of absences would be a column of nothing.
              </caption>
              <thead>
                <tr>
                  <th scope="col">Job</th>
                  <th scope="col">Due</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {neverRan.map((job) => (
                  <tr key={job.name}>
                    <th scope="row">{job.name}</th>
                    <td>{describeSchedule(job.scheduled_at_utc)}</td>
                    <td>
                      <Level level={job.level} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="scroll-hint">
            If this table is wider than your screen, it scrolls sideways rather than the
            page.
          </p>
        </div>
      ) : null}

      <Disclose brief="A job is one scheduled fetch, and this page asks each one whether it ran.">
        <p>
          One company&rsquo;s filings from SEC EDGAR, one series from FRED, one news feed.
          Each is meant to run at a fixed time and write rows into the database. This page
          asks one question of each — did it run inside the window, and what came back.
        </p>
        <p>
          <b>Ran ok</b> — it ran and reported success. <b>Needs attention</b> — it ran, or
          was due to, and something about the result was not what the job expected.{" "}
          <b>Failed</b> — it ran and returned an error. <b>Never ran</b> — it did not run
          in this window at all.
        </p>
      </Disclose>

      <Disclose brief="“Never ran” is an absence of information, not a failure.">
        <p>
          It is grey here rather than red on purpose. A job that has not run is not a
          broken job: on this machine the scheduler that would trigger them is not
          running, so jobs that are defined have simply never been started. Painting all
          of them red would say that many things had failed, which is not what the report
          says.
        </p>
        <p>
          On a machine with the scheduler running, the same state would mean something had
          gone wrong. The jobs that <i>are</i> running here are being triggered another
          way, and they report normally in the first table.
        </p>
      </Disclose>

      <Disclose brief="A job that ran and wrote no rows went and looked, and there was nothing new.">
        <p>
          Zero rows is not a failure and not a blank. It means the job went and looked and
          there was nothing new to store — which is a finding, and a different thing from
          never having looked. That is why it is written as a zero here, while a missing
          figure elsewhere on this site never is.
        </p>
      </Disclose>

      <Disclose brief="A schedule written “hourly, at 15 past” means every hour, at those minutes.">
        <p>
          The system stores a schedule in one of three ways and this page writes all three
          out in words. A fixed time means the job runs once a day at that hour. Hourly
          means it runs every hour, at those minutes past — so a news feed set to 15 past
          runs at 00:15, 01:15, 02:15 and so on. No fixed time means nothing runs it
          automatically; a person does, by hand.
        </p>
        <p>Every time on this page is UTC, including the last-run column.</p>
      </Disclose>

      <div className="source">
        <dl>
          <dt>Reported at</dt>
          <dd>{checkedAt}</dd>
          <dt>Window</dt>
          <dd>the {windowInWords(report.window_days)} before that moment</dd>
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
