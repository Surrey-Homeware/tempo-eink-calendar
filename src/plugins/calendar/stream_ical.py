from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from icalendar import Calendar, Event
import recurring_ical_events
from dateutil.parser import parse
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
import os
import logging

logger = logging.getLogger(__name__)


def _chunk_file_by_events(filepath, num_chunks=4):
    """Split file into roughly equal chunks, breaking on VEVENT boundaries."""
    file_size = os.path.getsize(filepath)
    chunk_size = file_size // num_chunks

    chunks = []
    with open(filepath, 'rb') as f:
        current_pos = 0
        f.seek(current_pos)

        for i in range(num_chunks):
            start_pos = current_pos
            if i == num_chunks - 1:
                # Last chunk gets the remainder
                end_pos = file_size
            else:
                # Seek to approximate chunk end
                target_pos = start_pos + chunk_size
                f.seek(target_pos)

                # Find next BEGIN:VEVENT or END:VEVENT boundary
                line = f.readline()
                while line:
                    line_str = line.decode('utf-8', errors='ignore').strip()
                    if line_str in ('END:VEVENT','END:VCALENDAR'):
                        break
                    line = f.readline()

                end_pos = f.tell()

            if start_pos < end_pos:
                chunks.append((start_pos, end_pos))
            current_pos = end_pos

    return chunks


def _process_chunk(args):
    """Worker function to process a file chunk."""
    filepath, start_pos, end_pos, start_dt, end_dt, return_type, default_tz = args

    # Helper functions (duplicated for worker process)
    def _to_dt(dtlike):
        if hasattr(dtlike, "dt"):
            dtlike = dtlike.dt
        if isinstance(dtlike, datetime):
            if dtlike.tzinfo is None:
                return dtlike.replace(tzinfo=ZoneInfo(default_tz))
            return dtlike
        else:
            return datetime.combine(dtlike, time.min, tzinfo=ZoneInfo(default_tz))

    def _event_block_to_calendar_bytes(event_block, vtimezones):
        parts = ["BEGIN:VCALENDAR", "VERSION:2.0"]
        parts.extend(vtimezones)
        parts.append(event_block)
        parts.append("END:VCALENDAR")
        cal_text = "\r\n".join(
            line if line.endswith(("\r", "\n")) else line
            for chunk in parts
            for line in chunk.splitlines()
        ) + "\r\n"
        return cal_text.encode("utf-8")

    def _event_to_dict(ev):
        def _get(prop):
            v = ev.get(prop)
            return getattr(v, "to_ical", lambda: v)() if v is not None else None

        dtstart = ev.get("DTSTART").dt if ev.get("DTSTART") else None
        dtend   = ev.get("DTEND").dt if ev.get("DTEND") else None
        return {
            "uid": (ev.get("UID") and ev.get("UID").to_ical().decode()) if ev.get("UID") else None,
            "summary": (ev.get("SUMMARY") and ev.get("SUMMARY").to_ical().decode()) if ev.get("SUMMARY") else None,
            "location": (ev.get("LOCATION") and ev.get("LOCATION").to_ical().decode()) if ev.get("LOCATION") else None,
            "description": (ev.get("DESCRIPTION") and ev.get("DESCRIPTION").to_ical().decode()) if ev.get("DESCRIPTION") else None,
            "dtstart": _to_dt(dtstart) if dtstart else None,
            "dtend": _to_dt(dtend) if dtend else None,
            "all_day": (not isinstance(dtstart, datetime)) if dtstart is not None else False,
        }

    results = []
    vtimezones = []
    tz_collect = False
    tz_lines = []

    inside_event = False
    occurring_in_range = False
    reoccurring_in_range = False
    start_year = str(start_dt.year)
    end_year = str(end_dt.year)
    ev_lines = []
    all_read = ""

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        f.seek(start_pos)
        bytes_read = 0

        for raw in f:
            bytes_read += len(raw.encode('utf-8'))
            if start_pos + bytes_read > end_pos:
                break

            line = raw.rstrip("\r\n")
            all_read += line + "\n"

            # Collect VTIMEZONE blocks
            if line == "BEGIN:VTIMEZONE":
                tz_collect = True
                tz_lines = [line]
                continue
            if tz_collect:
                tz_lines.append(line)
                if line == "END:VTIMEZONE":
                    vtimezones.append("\r\n".join(tz_lines))
                    tz_collect = False
                continue

            # Detect VEVENT blocks
            if line == "BEGIN:VEVENT":
                inside_event = True
                occurring_in_range = False
                reoccurring_in_range = False
                ev_lines = [line]
                continue

            if line.startswith("DTSTART"):
                if start_year in line or end_year in line:
                    occurring_in_range = True

            if line.startswith("RRULE:"):
                try:
                    start_util = line.index("UNTIL=")
                    until_value = line[start_util + len("UNTIL="):].split(";")[0]
                    end_date = parse(until_value)
                    if end_date.date() < datetime.now(ZoneInfo(default_tz)).date():
                        reoccurring_in_range = False
                    else:
                        reoccurring_in_range = True
                except ValueError:
                    reoccurring_in_range = True

            if inside_event:
                ev_lines.append(line)
                if line == "END:VEVENT":
                    inside_event = False

                    if not occurring_in_range and not reoccurring_in_range:
                        continue

                    mini_cal_bytes = _event_block_to_calendar_bytes("\r\n".join(ev_lines), vtimezones)
                    cal = Calendar.from_ical(mini_cal_bytes)

                    if reoccurring_in_range:
                        events = recurring_ical_events.of(cal).between(start_dt, end_dt)
                    else:
                        events = cal.walk()

                    ev = next((c for c in events if c.name == "VEVENT"), None)
                    if ev is None:
                        continue

                    dtstart_prop = ev.get("DTSTART")
                    if not dtstart_prop:
                        continue
                    dtstart = _to_dt(dtstart_prop)
                    in_range = (start_dt <= dtstart <= end_dt)

                    if in_range:
                        if return_type == "event":
                            results.append(ev)
                        else:
                            results.append(_event_to_dict(ev))

    return results


def load_ics_in_date_range(
    path,
    start=None,
    end=None,
    return_type="dict",          # "dict" or "event"
    default_tz="UTC",
    parallel=True,              # Enable parallel processing
    num_workers=4,              # Number of worker processes
):
    """
    Stream a large .ics and yield only events whose DTSTART falls in [start, end].
    Memory-friendly: never loads the full VCALENDAR. Can process in parallel.

    Parameters
    ----------
    path : str
        Path to the .ics file.
    start : datetime or date
        Range start (inclusive). Defaults to today at 00:00 in default_tz.
    end : datetime or date
        Range end (inclusive). Defaults to start + 30 days.
    return_type : "dict" | "event"
        "dict" yields lightweight dicts; "event" yields icalendar.Event objects.
    default_tz : str
        Fallback tz if a datetime is naive and no TZID is provided.
    parallel : bool
        Enable parallel processing across multiple CPU cores.
    num_workers : int
        Number of worker processes to use for parallel processing.
    """
    # ---- helpers ------------------------------------------------------------
    def _to_dt(dtlike):
        # Convert icalendar vDDDTypes .dt -> aware datetime
        if hasattr(dtlike, "dt"):
            dtlike = dtlike.dt
        if isinstance(dtlike, datetime):
            if dtlike.tzinfo is None:
                return dtlike.replace(tzinfo=ZoneInfo(default_tz))
            return dtlike
        else:
            # all-day DATE -> make it start-of-day in default_tz
            return datetime.combine(dtlike, time.min, tzinfo=ZoneInfo(default_tz))

    def _normalize_range(start, end):
        if start is None:
            start = datetime.now(ZoneInfo(default_tz)).replace(hour=0, minute=0, second=0, microsecond=0)
        elif not isinstance(start, datetime):
            start = datetime.combine(start, time.min, tzinfo=ZoneInfo(default_tz))
        elif start.tzinfo is None:
            start = start.replace(tzinfo=ZoneInfo(default_tz))

        if end is None:
            end = start + timedelta(days=30)
        elif not isinstance(end, datetime):
            end = datetime.combine(end, time.max, tzinfo=ZoneInfo(default_tz))
        elif end.tzinfo is None:
            end = end.replace(tzinfo=ZoneInfo(default_tz))
        return start, end

    def _event_block_to_calendar_bytes(event_block, vtimezones):
        # Build a tiny VCALENDAR containing the collected VTIMEZONEs + this VEVENT
        parts = ["BEGIN:VCALENDAR", "VERSION:2.0"]
        parts.extend(vtimezones)               # already BEGIN/END VTIMEZONE blocks
        parts.append(event_block)              # the full BEGIN:VEVENT...END:VEVENT
        parts.append("END:VCALENDAR")
        # Normalize line endings for safety
        cal_text = "\r\n".join(
            line if line.endswith(("\r", "\n")) else line
            for chunk in parts
            for line in chunk.splitlines()
        ) + "\r\n"
        return cal_text.encode("utf-8")

    def _event_to_dict(ev):
        def _get(prop):
            v = ev.get(prop)
            return getattr(v, "to_ical", lambda: v)() if v is not None else None

        dtstart = ev.get("DTSTART").dt if ev.get("DTSTART") else None
        dtend = ev.get("DTEND").dt if ev.get("DTEND") else None
        return {
            "uid": (ev.get("UID") and ev.get("UID").to_ical().decode()) if ev.get("UID") else None,
            "summary": (ev.get("SUMMARY") and ev.get("SUMMARY").to_ical().decode()) if ev.get("SUMMARY") else None,
            "location": (ev.get("LOCATION") and ev.get("LOCATION").to_ical().decode()) if ev.get("LOCATION") else None,
            "description": (ev.get("DESCRIPTION") and ev.get("DESCRIPTION").to_ical().decode()) if ev.get("DESCRIPTION") else None,
            "dtstart": _to_dt(dtstart) if dtstart else None,
            "dtend": _to_dt(dtend) if dtend else None,
            "all_day": (not isinstance(dtstart, datetime)) if dtstart is not None else False,
        }

    start, end = _normalize_range(start, end)

    logging.info(f"Processing events in {path} for date range {start} to {end}")

    if parallel and num_workers > 1:
        # Use parallel processing
        logging.info(f"Using parallel processing with {num_workers} workers")

        # Split file into chunks
        chunks = _chunk_file_by_events(path, num_workers)
        if not chunks:
            return

        # Prepare arguments for worker processes
        worker_args = [
            (path, start_pos, end_pos, start, end, return_type, default_tz)
            for start_pos, end_pos in chunks
        ]

        # Process chunks in parallel
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            chunk_results = executor.map(_process_chunk, worker_args)

        # Yield results from all chunks
        for chunk_result in chunk_results:
            for event in chunk_result:
                yield event

    else:
        # Use original sequential processing
        vtimezones = []            # collect any VTIMEZONE blocks for TZID resolution
        tz_collect = False
        tz_lines = []

        inside_event = False
        occurring_in_range = False
        reoccurring_in_range = False
        start_year = str(start.year)
        end_year = str(end.year)
        ev_lines = []

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.rstrip("\r\n")

                # Collect VTIMEZONE blocks (once; cheap)
                if line == "BEGIN:VTIMEZONE":
                    tz_collect = True
                    tz_lines = [line]
                    continue
                if tz_collect:
                    tz_lines.append(line)
                    if line == "END:VTIMEZONE":
                        # keep the whole block as a single text chunk
                        vtimezones.append("\r\n".join(tz_lines))
                        tz_collect = False
                    continue  # don't let timezone lines fall through

                # Detect VEVENT blocks
                if line == "BEGIN:VEVENT":
                    inside_event = True
                    occurring_in_range = False
                    reoccurring_in_range = False
                    ev_lines = [line]
                    continue

                # include events plausibly in our date range
                if line.startswith("DTSTART"):
                    if start_year in line or end_year in line:
                        occurring_in_range = True

                # Include events with reoccurrences in our date range
                if line.startswith("RRULE:"):
                    try:
                        start_util = line.index("UNTIL=")
                        until_value = line[start_util + len("UNTIL="):].split(";")[0]
                        end_date = parse(until_value)
                        if end_date.date() < datetime.now(ZoneInfo(default_tz)).date():
                            reoccurring_in_range = False
                        else:
                            reoccurring_in_range = True
                    except ValueError:
                        reoccurring_in_range = True

                if inside_event:
                    ev_lines.append(line)
                    if line == "END:VEVENT":
                        inside_event = False

                        # To save processing time on a slow Pi Zero with a large calendar,
                        # don't process entries that aren't even from the correct year
                        if not occurring_in_range and not reoccurring_in_range:
                            continue

                        # We have a complete VEVENT block -> make a tiny calendar and parse just this one
                        mini_cal_bytes = _event_block_to_calendar_bytes("\r\n".join(ev_lines), vtimezones)
                        cal = Calendar.from_ical(mini_cal_bytes)

                        if reoccurring_in_range:
                            events = recurring_ical_events.of(cal).between(start, end)
                        else:
                            events = cal.walk()
                        # There should be exactly one event component in this tiny calendar
                        ev = next((c for c in events if c.name == "VEVENT"), None)
                        if ev is None:
                            continue

                        # Filter by DTSTART (and optionally recurrences note below)
                        dtstart_prop = ev.get("DTSTART")
                        if not dtstart_prop:
                            continue
                        dtstart = _to_dt(dtstart_prop)
                        in_range = (start <= dtstart <= end)

                        if in_range:
                            if return_type == "event":
                                yield ev
                            else:
                                yield _event_to_dict(ev)
