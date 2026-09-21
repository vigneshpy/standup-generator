"""Run: python3 test_standup.py"""
from datetime import datetime
import standup as s

# 1 + 2: prefix stripping and one format
assert s.normalize_task("[RSNT-692] fix: enforce $2,500 minimum") == "RSNT-692 enforce $2,500 minimum"
assert s.normalize_task("[RSNT-475] trid subproduct label") == "RSNT-475 trid subproduct label"
assert s.normalize_task("feat(ui): [CLIENT-1] thing") == "CLIENT-1 thing"
assert s.normalize_task("RSNT-475: trid label") == "RSNT-475 trid label"
assert s.normalize_task("chore: bump deps") == "bump deps"
assert s.normalize_task("Fix crash in RSNT-12 flow") == "Fix crash in RSNT-12 flow"
assert s.normalize_task("CD Rate ", key="RSNT-666") == "RSNT-666 CD Rate"
assert s.task_key("Reviewed PR: CLIENT-800 x") == "CLIENT-800"

# 4 + header
mon, tue, sun = datetime(2026, 9, 21), datetime(2026, 9, 22), datetime(2026, 9, 20)
assert s.get_last_workday(mon).date() == datetime(2026, 9, 18).date()
assert s.get_last_workday(tue).date() == datetime(2026, 9, 21).date()
assert s.get_last_workday(sun).date() == datetime(2026, 9, 18).date()
assert s.period_header(datetime(2026, 9, 18), today=mon) == "Last working day (Friday):"
assert s.period_header(datetime(2026, 9, 21), today=tue) == "Yesterday:"
assert s.period_header(datetime(2026, 9, 17), today=tue) == "Last working day (Thursday):"  # --since after holiday

# 6 + 8: interactive editing via scripted input
import builtins
def feed(*lines):
    it = iter(lines)
    builtins.input = lambda _="": next(it)

feed("-2,write docs", "")
assert s.edit_list(["a", "b", "c"], "t") == ["a", "c", "write docs"]

def tk(key, status, summary="x"):
    return {"key": key, "fields": {"summary": summary, "status": {"name": status}}}
tickets = [tk("AB-1", "ALLOCATED"), tk("AB-2", "Code In Review"), tk("AB-3", "DEPLOYED TO DEV")]

feed("")  # accept defaults: A-1 carried over, A-2 in-progress status
assert s.select_today(tickets, ["AB-1 done thing"]) == ["AB-1 x", "AB-2 x"]
feed("3", "")  # exact pick replaces defaults
assert s.select_today(tickets, ["AB-1 done thing"]) == ["AB-3 x"]
feed("+3,-1,prod release", "")  # toggles + custom
assert s.select_today(tickets, ["AB-1 done thing"]) == ["AB-2 x", "AB-3 x", "prod release"]
feed("+3,prod release", "-4", "")  # remove a custom entry
assert s.select_today(tickets, []) == ["AB-2 x", "AB-3 x"]

print("all checks passed")
