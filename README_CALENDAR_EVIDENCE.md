# Calendar evidence and date confidence

The report and `/calendar` use a dated snapshot that distinguishes publisher schedules from Nasdaq calendar estimates. The existing daily agent refreshes and reviews that snapshot before building reports and trade plans. No additional AI API call or subscription is required.

## Economic releases

The bot reads the official [BLS iCalendar](https://www.bls.gov/schedule/news_release/bls.ics), [BEA iCalendar](https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics), [Labor Department claims publication schedule](https://oui.doleta.gov/unemploy/claims_arch.asp), [Fed event calendar](https://www.federalreserve.gov/json/calendar.json), and [University of Michigan's next-release notice](https://www.sca.isr.umich.edu/). BLS's `US-Eastern` timezone is normalized to `America/New_York`. BEA UTC timestamps and DOL holiday exceptions retain their dates and adjust for daylight saving time.

BEA's abbreviated national `GDP (Advance/Second/Third Estimate)` titles are recognized. Regional and Puerto Rico GDP cannot confirm the national release, and quarterly PCE prices remain distinct from monthly PCE price indexes. The Fed supplies separate dated statement/decision, press-conference and minutes entries. Its announcement-day field is used instead of the meeting's starting date; missing clocks are never filled with default times. Fed announcement clocks use US Eastern Time, consistent with its [policy-rate explanation](https://www.federalreserve.gov/economy-at-a-glance-policy-rate.htm). Michigan's next-release notice must explicitly supply one full date, a matching weekday and an Eastern clock. It confirms that notice only, rather than every future survey date.

A matching publisher release establishes the scheduled date and time. Actual, consensus and previous values still come from Nasdaq and retain that separate provenance. The bot does not infer a timezone from Nasdaq's field name `gmt`. For example:

```text
08:30 EDT [DOL] - Initial Jobless Claims - actual ... | expected ... | previous ...
Time unverified (source 09:45) - S&P Global Manufacturing PMI - ...
```

Unsupported releases, inaccessible publisher schedules and ambiguous dates remain explicitly unverified. A date that conflicts with a nearby matching publisher release cannot supply actual, expected or previous values. Future actuals are withheld before caching, including before a verified release later on the same day. Publisher schedules can still supply release dates and times when Nasdaq's economic feed is unavailable or omits a scheduled release, with forecast values left unavailable. Omitted releases and publisher failures remain visible in calendar coverage notes. An empty result describes the available feeds rather than claiming there are no macro events that day.

S&P Global's public PMI calendar returned HTTP 403 during deployment verification. This update therefore keeps PMI as Nasdaq coverage with unverified timing; it does not invent a publisher clock or hard-code the October release date. Other unsupported economic schedules also remain unverified.

Dates in calendar headings use the US calendar. Verified times convert to `REPORT_TIMEZONE`; when conversion crosses midnight, the displayed time includes its converted date. Unverified times keep their original source clock without a conversion.

## Earnings

Nasdaq [describes its earnings dates as algorithm-derived estimates](https://www.nasdaq.com/market-activity). Calendar dates are therefore labeled as estimates pending company confirmation. Before-market and after-market labels refer to the US market session. This update does not claim to verify every company's investor-relations schedule or turn a webcast time into an earnings-release time.

`/tradeplan SYMBOL` and `/scorecard SYMBOL` show matching estimated earnings dates from the same snapshot. Numerical stock scores and rankings remain separate from this explanatory calendar evidence.

## Agent and cache

`/rundailyagent` gains a Calendar Review step. Calendar Evidence also registers with the existing intelligence context registry. Readers use cached evidence and do not fetch sources or send Telegram messages. The report's source list marks Calendar Evidence active when a current snapshot is present.

The default runtime file is `data/calendar_snapshot.json`; `CALENDAR_STATE_FILE` can override it. Calendar views refresh after 30 minutes. Cached company and agent reviews expire after six hours and show only current or future US calendar dates. Missing, malformed, future-dated or expired snapshots cannot supply current context. Writes use an atomic replacement. Deployment preflight and installer checks use temporary state files.

The economic query-date adjustment remains controlled by the existing `CALENDAR_ECONOMIC_DATE_OFFSET`. Nasdaq's `asOf` is not used as an event date. Publisher matching adds independent date verification where covered.

## Checks

```text
python scripts/check_calendar_evidence.py
python scripts/check_daily_agent_delivery.py
python scripts/check_report_consistency.py
```

Checks use synthetic schedules and mocked delivery. The calendar check also runs in deployment preflight and the existing Linux/Windows GitHub regression workflow.
