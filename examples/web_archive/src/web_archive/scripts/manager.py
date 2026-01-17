#!/usr/bin/env python3
"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

from p40_flowbase import (
    BaseDataObjectManager,
    apply_style,
)

from web_archive.config import settings
from web_archive.data import (
    AgentClusterSpecs,
    ClusterSpecs,
    URLSample,
    WMSnapshotAgentExtractionDB,
    WMSnapshotContent,
    WMSnapshotContentDB,
    WMSnapshotContentLLMExtractionDB,
    WMSnapshotFiles,
    WMSnapshotURLs,
    WMSnapshotURLsDB,
)


class WebArchiveManager(BaseDataObjectManager):
    """Manager for web archive data objects."""

    OBJECTS = {
        URLSample.id: URLSample,
        WMSnapshotURLsDB.id: WMSnapshotURLsDB,
        WMSnapshotURLs.id: WMSnapshotURLs,
        WMSnapshotContentDB.id: WMSnapshotContentDB,
        WMSnapshotContent.id: WMSnapshotContent,
        WMSnapshotFiles.id: WMSnapshotFiles,
        WMSnapshotContentLLMExtractionDB.id: WMSnapshotContentLLMExtractionDB,
        ClusterSpecs.id: ClusterSpecs,
        WMSnapshotAgentExtractionDB.id: WMSnapshotAgentExtractionDB,
        AgentClusterSpecs.id: AgentClusterSpecs,
    }

    app_name = "web_archive_manager"
    app_help = "Manage web archive data objects"

    @property
    def data_local_tmp(self) -> str:
        return settings.data_local_tmp

    @property
    def anthropic_api_key(self) -> str | None:
        return settings.anthropic_api_key

    @property
    def google_api_key(self) -> str | None:
        return settings.google_api_key

    @property
    def openai_api_key(self) -> str | None:
        return settings.openai_api_key

    def configure_styles(self) -> None:
        apply_style("style_1")


manager = WebArchiveManager()
app = manager.app


if __name__ == "__main__":
    manager.run()
