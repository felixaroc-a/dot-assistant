"""Pipeline de documentos / CV (FREE-DC01–DC06)."""

from app.application.documents.pipeline import (
    chunk_by_paragraph,
    chunk_by_section,
    chunk_text,
    export_results,
    export_to_excel,
    extract_from_path,
    extract_from_text,
    extract_from_url,
    merge_exports,
    process_folder,
    run_doc_pipeline_if_enabled,
    stats_report,
    supported_path_suffixes,
)

__all__ = [
    "chunk_by_paragraph",
    "chunk_by_section",
    "chunk_text",
    "export_results",
    "export_to_excel",
    "extract_from_path",
    "extract_from_text",
    "extract_from_url",
    "merge_exports",
    "process_folder",
    "run_doc_pipeline_if_enabled",
    "stats_report",
    "supported_path_suffixes",
]
