"""Reconciliation report for one processed file (D10, D14, D24)."""

from contribflow.pipeline import FileResult


def summary_line(result: FileResult) -> str:
    line = f"{result.file_name}  {result.outcome}  records={result.record_count}"
    if result.outcome == "rejected":
        line += f"  file_reasons={','.join(result.file_reasons)}"
    else:
        line += (
            f"  accepted={result.count('accepted')}"
            f"  rejected={result.count('rejected')}"
            f"  already_posted={result.count('already_posted')}"
        )
    if result.resubmitted:
        line += "  (resubmitted: identical file, nothing changed)"
    return line


def format_report(result: FileResult) -> str:
    lines = [summary_line(result)]
    for record in result.records:
        if record.outcome == "rejected":
            lines.append(
                f"  row {record.source_row:>4}  {record.employee_id or '-':<10}  "
                + ", ".join(record.reasons)
            )
    return "\n".join(lines)
