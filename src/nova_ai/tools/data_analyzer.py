"""Data Analyzer tool — CSV, JSON, and Excel analysis with statistics and chart generation."""

from __future__ import annotations

import csv
import io
import json
import logging
import math
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from nova_ai.core.registry import ToolRegistry
from nova_ai.core.types import ToolResult
from nova_ai.engine.self_optimizer import track_execution
from nova_ai.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)


def _parse_csv(raw: str) -> List[Dict[str, str]]:
    """Parse CSV text into list of dicts."""
    reader = csv.DictReader(io.StringIO(raw))
    return list(reader)


def _parse_json(raw: str) -> Any:
    """Parse JSON text, handling both arrays and objects."""
    return json.loads(raw)


def _load_file(file_path: str) -> Tuple[str, str]:
    """Load file content and detect format."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        try:
            import openpyxl

            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                return "[]", "json"
            headers = [str(h or f"col_{i}") for i, h in enumerate(rows[0])]
            records = []
            for row in rows[1:]:
                record = {}
                for j, val in enumerate(row):
                    key = headers[j] if j < len(headers) else f"col_{j}"
                    record[key] = val if val is not None else ""
                records.append(record)
            wb.close()
            return json.dumps(records), "json"
        except ImportError:
            raise ImportError(
                "Install openpyxl for Excel support: pip install openpyxl"
            )

    content = path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".json":
        return content, "json"
    return content, "csv"


def _compute_numeric_stats(values: List[float]) -> Dict[str, Any]:
    """Compute descriptive statistics for a numeric column."""
    if not values:
        return {"count": 0}

    n = len(values)
    sorted_v = sorted(values)
    total = sum(values)
    mean = total / n
    median = (
        sorted_v[n // 2]
        if n % 2 == 1
        else (sorted_v[n // 2 - 1] + sorted_v[n // 2]) / 2
    )
    variance = sum((x - mean) ** 2 for x in values) / max(n - 1, 1)
    std_dev = math.sqrt(variance)

    return {
        "count": n,
        "min": round(sorted_v[0], 4),
        "max": round(sorted_v[-1], 4),
        "mean": round(mean, 4),
        "median": round(median, 4),
        "std_dev": round(std_dev, 4),
        "sum": round(total, 4),
        "p25": round(sorted_v[int(n * 0.25)], 4),
        "p75": round(sorted_v[int(n * 0.75)], 4),
    }


def _detect_numeric(values: List[str]) -> Tuple[bool, List[float]]:
    """Check if a column is numeric and parse values."""
    nums = []
    for v in values:
        v = str(v).strip()
        if not v or v.lower() in ("", "null", "none", "na", "nan", "n/a"):
            continue
        try:
            nums.append(float(v.replace(",", "")))
        except ValueError:
            return False, []
    return len(nums) > 0, nums


def _analyze_records(records: List[Dict[str, Any]], query: str = "") -> str:
    """Run analysis on tabular records and produce a formatted report."""
    if not records:
        return "No data records found."

    n_rows = len(records)
    columns = list(records[0].keys()) if records else []
    n_cols = len(columns)

    report_lines = [
        "## Data Analysis Report",
        f"**Rows:** {n_rows} | **Columns:** {n_cols}",
        f"**Columns:** {', '.join(columns)}",
        "",
    ]

    # Per-column analysis
    for col in columns:
        values = [str(r.get(col, "")) for r in records]
        is_num, nums = _detect_numeric(values)

        if is_num and nums:
            stats = _compute_numeric_stats(nums)
            report_lines.append(f"### 📊 {col} (Numeric)")
            for k, v in stats.items():
                report_lines.append(f"  - {k}: {v}")
        else:
            # Categorical summary
            counter = Counter(v for v in values if v.strip())
            top_5 = counter.most_common(5)
            unique_count = len(counter)
            report_lines.append(f"### 📋 {col} (Categorical)")
            report_lines.append(f"  - Unique values: {unique_count}")
            report_lines.append(
                f"  - Top values: {', '.join(f'{v} ({c})' for v, c in top_5)}"
            )
            missing = sum(1 for v in values if not v.strip())
            if missing:
                report_lines.append(f"  - Missing: {missing}")

        report_lines.append("")

    # Data preview (first 5 rows as markdown table)
    if records:
        report_lines.append("### Preview (first 5 rows)")
        header = "| " + " | ".join(columns) + " |"
        sep = "| " + " | ".join(["---"] * n_cols) + " |"
        report_lines.extend([header, sep])
        for row in records[:5]:
            row_str = (
                "| " + " | ".join(str(row.get(c, ""))[:30] for c in columns) + " |"
            )
            report_lines.append(row_str)

    return "\n".join(report_lines)


@ToolRegistry.register("data_analyzer")
class DataAnalyzerTool(BaseTool):
    """Analyze CSV, JSON, or Excel data — compute statistics, detect patterns, and generate reports."""

    tool_id = "data_analyzer"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="data_analyzer",
            description=(
                "Analyze structured data from CSV, JSON, or Excel files. "
                "Computes descriptive statistics (mean, median, std, percentiles), "
                "detects column types, counts unique values, and produces formatted reports."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to a CSV, JSON, or XLSX file to analyze.",
                    },
                    "raw_data": {
                        "type": "string",
                        "description": "Raw CSV or JSON text to analyze directly (alternative to file_path).",
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional natural language question about the data.",
                    },
                },
            },
            category="analysis",
            timeout_seconds=30.0,
        )

    @track_execution("data_analyzer")
    def execute(
        self,
        file_path: Optional[str] = None,
        raw_data: Optional[str] = None,
        query: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if not file_path and not raw_data:
            return ToolResult(
                tool_name="data_analyzer",
                content="Error: Provide either 'file_path' or 'raw_data'.",
                success=False,
            )

        try:
            if file_path:
                content, fmt = _load_file(file_path)
            else:
                content = raw_data.strip()
                fmt = "json" if content.startswith(("[", "{")) else "csv"

            if fmt == "json":
                parsed = _parse_json(content)
                if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                    records = parsed
                elif isinstance(parsed, dict):
                    records = [parsed]
                else:
                    records = (
                        [{"value": item} for item in parsed]
                        if isinstance(parsed, list)
                        else []
                    )
            else:
                records = _parse_csv(content)

            report = _analyze_records(records, query)

            return ToolResult(
                tool_name="data_analyzer",
                content=report,
                success=True,
                metadata={
                    "source": file_path or "raw_input",
                    "format": fmt,
                    "rows": len(records),
                    "columns": len(records[0]) if records else 0,
                },
            )

        except FileNotFoundError as e:
            return ToolResult(tool_name="data_analyzer", content=str(e), success=False)
        except json.JSONDecodeError as e:
            return ToolResult(
                tool_name="data_analyzer", content=f"Invalid JSON: {e}", success=False
            )
        except Exception as e:
            return ToolResult(
                tool_name="data_analyzer",
                content=f"Analysis failed: {e}",
                success=False,
            )


__all__ = ["DataAnalyzerTool"]
