"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import json
import re
import uuid
from datetime import (
    UTC,
    datetime,
)
from enum import Enum
from typing import (
    Any,
    List,
    Optional,
)

import pandas as pd
import pydantic as pyd
from sqlmodel import (
    Field,
    SQLModel,
)

import p40_flowbase as fb


class URLVersions(Enum):
    UNIS_1 = fb.DataObjectVersion(
        id="unis_1",
        name="University URLs (Group 1)",
        description="URLs from manually shortlisted universities (Group 1)",
    )
    UNIS_1_TEST = fb.DataObjectVersion(
        id="unis_1_test",
        name="Test university (Group 1)",
        description="URLs for one university from University URLs (Group 1)",
    )


class URLSampleStruct(pyd.BaseModel):
    org: str = pyd.Field(
        title="Organization",
        description="Organization identifier (usually domain name)",
        json_schema_extra={"units": "text"},
    )
    url: str = pyd.Field(
        title="URL",
        description="HTTP/HTTPS URL to one of the pages that belong to the organization",
        json_schema_extra={"units": "text"},
    )


class URLSample(fb.TableDataObject):
    id: str = "url_sample"
    description: str = "Sample of organization URLs for web archive retrieval"
    supported_versions = tuple(URLVersions)
    schema = URLSampleStruct

    def _make_default(self):
        """Create sample table with URLs for the specified version."""
        if self.version == URLVersions.UNIS_1:
            urls = [
                {"org": "asu.edu", "url": "https://asurc.atlassian.net/wiki/spaces/RC/overview"},
                {"org": "asu.edu", "url": "https://cores.research.asu.edu/research-computing/user-guide"},
                {"org": "clemson.edu", "url": "https://docs.rcd.clemson.edu/palmetto/compute/hardware/"},
                {"org": "clemson.edu", "url": "https://www.palmetto.clemson.edu/palmetto/userguide_palmetto_overview.html"},
                {"org": "iastate.edu", "url": "https://www.hpc.iastate.edu/systems"},
                {"org": "uvm.edu", "url": "https://www.uvm.edu/vacc/cluster-specs"},
                {"org": "virginia.edu", "url": "http://arcs.virginia.edu/rivanna"},
                {"org": "virginia.edu", "url": "https://www.rc.virginia.edu/userinfo/hpc/"},
                {"org": "virginia.edu", "url": "https://www.rc.virginia.edu/userinfo/rivanna/overview/"},
            ]
        elif self.version == URLVersions.UNIS_1_TEST:
            urls = [
                {"org": "iastate.edu", "url": "https://www.hpc.iastate.edu/systems"},
            ]
        else:
            raise ValueError(f"Unknown version '{self.version.value.id}'")

        df = pd.DataFrame(urls)
        df = df.convert_dtypes(dtype_backend="pyarrow")
        df.to_parquet(self.path_to_format(fb.TableFormat.PARQUET), index=False)


class WMSnapshotURLsHTTPRequestGroup(SQLModel, table=True):
    __tablename__ = "wm_snapshot_urls_http_request_groups"
    __table_args__ = {"extend_existing": True}

    http_request_group_id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_by_class: str


class WMSnapshotURLsHTTPRequestExtra(SQLModel, table=True):
    __tablename__ = "wm_snapshot_urls_http_request_extra"
    __table_args__ = {"extend_existing": True}

    http_request_extra_id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    org: str
    url: str
    year: int


class WMSnapshotURLsDB(fb.HTTPRequestsDBMixin, fb.DBDataObject):
    id: str = "wm_snapshot_urls_db"
    description: str = "Database for logging and executing HTTP requests to Wayback Machine Availability API"
    supported_versions = tuple(URLVersions)
    schema: List[Any] = [
        WMSnapshotURLsHTTPRequestGroup,
        WMSnapshotURLsHTTPRequestExtra,
        fb.HTTPRequest,
    ]

    async def _populate_http_requests(self) -> uuid.UUID:
        """Populate database with Wayback Machine Availability API requests."""
        sample_obj = URLSample(version=self.version)

        if not sample_obj.path_to_format(fb.TableFormat.PARQUET).exists():
            sample_obj.make(replace=False)

        urls_df = sample_obj.pdf

        headers = json.dumps({"User-Agent": "research-project/1.0"})

        group = WMSnapshotURLsHTTPRequestGroup(created_by_class=self.__class__.__name__)

        async with self.session_factory() as session:
            session.add(group)
            await session.commit()
            await session.refresh(group)

        timestamps = [f"{year}0701000000" for year in range(2015, 2026)]

        availability_requests = []
        for _, row in urls_df.iterrows():
            org = row["org"]
            url = row["url"]

            for timestamp in timestamps:
                year = int(timestamp[:4])
                availability_url = f"https://archive.org/wayback/available?url={url}&timestamp={timestamp}"

                extra = WMSnapshotURLsHTTPRequestExtra(
                    org=org,
                    url=url,
                    year=year,
                )

                async with self.session_factory() as session:
                    session.add(extra)
                    await session.commit()
                    await session.refresh(extra)

                availability_requests.append({
                    "request_url": availability_url,
                    "request_method": "GET",
                    "request_headers": headers,
                    "http_request_group_id": group.http_request_group_id,
                    "http_request_extra_id": extra.http_request_extra_id,
                })

        await self._add_http_requests(availability_requests)

        return group.http_request_group_id


class WMSnapshotURLsStruct(pyd.BaseModel):
    org: str = pyd.Field(
        title="Organization",
        description="Organization for which snapshot was requested",
        json_schema_extra={"units": "text"},
    )
    url: str = pyd.Field(
        title="URL",
        description="URL for which snapshot was requested",
        json_schema_extra={"units": "text"},
    )
    year: int = pyd.Field(
        title="Year",
        description="Year for which snapshot was requested",
        json_schema_extra={"units": "year"},
    )
    snapshot_url: Optional[str] = pyd.Field(
        title="Snapshot URL",
        description="URL of the snapshot returned by Availability API",
        json_schema_extra={"units": "text"},
    )


class WMSnapshotURLs(fb.TableDataObject):
    id: str = "wm_snapshot_urls"
    description: str = "Wayback Machine snapshot URLs extracted from Availability API responses"
    supported_versions = tuple(URLVersions)
    schema = WMSnapshotURLsStruct

    def _make_default(self):
        """Extract snapshot URLs from Wayback Machine Availability API responses."""
        import asyncio

        asyncio.run(self._extract_from_db())

    async def _extract_from_db(self):
        """Extract snapshot URLs from database."""
        from sqlmodel import select

        db = WMSnapshotURLsDB(version=self.version)

        if not db.path_to_format(fb.DBFormat.SQLITE).exists():
            await db.make_async()

        async with db.session_factory() as session:
            statement = (
                select(fb.HTTPRequest, WMSnapshotURLsHTTPRequestExtra)
                .join(
                    WMSnapshotURLsHTTPRequestExtra,
                    fb.HTTPRequest.http_request_extra_id == WMSnapshotURLsHTTPRequestExtra.http_request_extra_id,
                )
                .where(
                    fb.HTTPRequest.response_status == 200,
                    fb.HTTPRequest.requested_at_utc.is_not(None),
                )
                .order_by(fb.HTTPRequest.requested_at_utc.desc())
            )
            result = await session.exec(statement)
            rows = result.all()

        records = []
        seen_keys = set()

        for http_request, extra in rows:
            key = (extra.org, extra.url, extra.year)

            if key in seen_keys:
                continue

            seen_keys.add(key)

            snapshot_url = None
            if http_request.response_body_text:
                try:
                    response_data = json.loads(http_request.response_body_text)
                    archived_snapshots = response_data.get("archived_snapshots", {})
                    closest = archived_snapshots.get("closest", {})
                    snapshot_url = closest.get("url")
                except (json.JSONDecodeError, KeyError):
                    pass

            records.append({
                "org": extra.org,
                "url": extra.url,
                "year": extra.year,
                "snapshot_url": snapshot_url,
            })

        df = pd.DataFrame(records)
        df = df.convert_dtypes(dtype_backend="pyarrow")
        df.to_parquet(self.path_to_format(fb.TableFormat.PARQUET), index=False)

        await db.close()


class WMSnapshotContentHTTPRequestGroup(SQLModel, table=True):
    __tablename__ = "wm_snapshot_content_http_request_groups"
    __table_args__ = {"extend_existing": True}

    http_request_group_id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_by_class: str


class WMSnapshotContentHTTPRequestExtra(SQLModel, table=True):
    __tablename__ = "wm_snapshot_content_http_request_extra"
    __table_args__ = {"extend_existing": True}

    http_request_extra_id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    org: str
    url: str
    year: int
    snapshot_url: str


class WMSnapshotContentDB(fb.HTTPRequestsDBMixin, fb.DBDataObject):
    id: str = "wm_snapshot_content_db"
    description: str = "Database for logging and executing HTTP requests to retrieve Wayback Machine snapshot content"
    supported_versions = tuple(URLVersions)
    schema: List[Any] = [
        WMSnapshotContentHTTPRequestGroup,
        WMSnapshotContentHTTPRequestExtra,
        fb.HTTPRequest,
    ]

    async def _populate_http_requests(self) -> uuid.UUID:
        """Populate database with snapshot content retrieval requests."""
        snapshots_obj = WMSnapshotURLs(version=self.version)

        if not snapshots_obj.path_to_format(fb.TableFormat.PARQUET).exists():
            snapshots_obj.make(replace=False)

        snapshots_df = snapshots_obj.pdf

        snapshots_df = snapshots_df[snapshots_df["snapshot_url"].notna()]

        headers = json.dumps({"User-Agent": "research-project/1.0"})

        group = WMSnapshotContentHTTPRequestGroup(created_by_class=self.__class__.__name__)

        async with self.session_factory() as session:
            session.add(group)
            await session.commit()
            await session.refresh(group)

        content_requests = []
        for _, row in snapshots_df.iterrows():
            org = row["org"]
            url = row["url"]
            year = int(row["year"])
            snapshot_url = row["snapshot_url"]

            modified_url = snapshot_url.replace("/web/", "/web/", 1)
            match = re.match(r"(https://web\.archive\.org/web/\d{14})(/.+)", modified_url)
            if match:
                modified_url = f"{match.group(1)}id_{match.group(2)}"

            extra = WMSnapshotContentHTTPRequestExtra(
                org=org,
                url=url,
                year=year,
                snapshot_url=snapshot_url,
            )

            async with self.session_factory() as session:
                session.add(extra)
                await session.commit()
                await session.refresh(extra)

            content_requests.append({
                "request_url": modified_url,
                "request_method": "GET",
                "request_headers": headers,
                "http_request_group_id": group.http_request_group_id,
                "http_request_extra_id": extra.http_request_extra_id,
            })

        await self._add_http_requests(content_requests)

        return group.http_request_group_id


class WMSnapshotContentStruct(pyd.BaseModel):
    org: str = pyd.Field(
        title="Organization",
        description="Organization for which snapshot was retrieved",
        json_schema_extra={"units": "text"},
    )
    url: str = pyd.Field(
        title="URL",
        description="URL for which snapshot was retrieved",
        json_schema_extra={"units": "text"},
    )
    year: int = pyd.Field(
        title="Year",
        description="Year for which snapshot was retrieved",
        json_schema_extra={"units": "year"},
    )
    snapshot_url: str = pyd.Field(
        title="Snapshot URL",
        description="URL of the snapshot",
        json_schema_extra={"units": "text"},
    )
    snapshot_content: Optional[str] = pyd.Field(
        title="Snapshot Content",
        description="HTML content of the snapshot",
        json_schema_extra={"units": "text"},
    )


class WMSnapshotContent(fb.TableDataObject):
    id: str = "wm_snapshot_content"
    description: str = "Wayback Machine snapshot content retrieved from archived pages"
    supported_versions = tuple(URLVersions)
    schema = WMSnapshotContentStruct

    def _make_default(self):
        """Extract snapshot content from HTTP responses."""
        import asyncio

        asyncio.run(self._extract_from_db())

    async def _extract_from_db(self):
        """Extract snapshot content from database."""
        from sqlmodel import select

        db = WMSnapshotContentDB(version=self.version)

        if not db.path_to_format(fb.DBFormat.SQLITE).exists():
            await db.make_async()

        async with db.session_factory() as session:
            statement = (
                select(fb.HTTPRequest, WMSnapshotContentHTTPRequestExtra)
                .join(
                    WMSnapshotContentHTTPRequestExtra,
                    fb.HTTPRequest.http_request_extra_id == WMSnapshotContentHTTPRequestExtra.http_request_extra_id,
                )
                .where(fb.HTTPRequest.requested_at_utc.is_not(None))
                .order_by(fb.HTTPRequest.requested_at_utc.desc())
            )
            result = await session.exec(statement)
            rows = result.all()

        records = []
        seen_keys = set()

        for http_request, extra in rows:
            key = (extra.org, extra.url, extra.year, extra.snapshot_url)

            if key in seen_keys:
                continue

            seen_keys.add(key)

            snapshot_content = None
            if http_request.response_status == 200 and http_request.response_body_text:
                snapshot_content = http_request.response_body_text

            records.append({
                "org": extra.org,
                "url": extra.url,
                "year": extra.year,
                "snapshot_url": extra.snapshot_url,
                "snapshot_content": snapshot_content,
            })

        df = pd.DataFrame(records)
        df = df.convert_dtypes(dtype_backend="pyarrow")
        df.to_parquet(self.path_to_format(fb.TableFormat.PARQUET), index=False)

        await db.close()


class WMSnapshotFiles(fb.CompositeDataObject):
    id: str = "wm_snapshot_files"
    description: str = "Wayback Machine snapshot HTML files organized by org/url/year"
    supported_versions = tuple(URLVersions)

    def _make_default(self):
        """Save snapshot content to individual HTML files."""
        import asyncio

        asyncio.run(self._save_files())

    async def _save_files(self):
        """Save snapshot content from WMSnapshotContent to files."""
        import urllib.parse

        snapshot_obj = WMSnapshotContent(version=self.version)

        if not snapshot_obj.path_to_format(fb.TableFormat.PARQUET).exists():
            snapshot_obj.make(replace=False)

        snapshots_df = snapshot_obj.pdf
        snapshots_df = snapshots_df[snapshots_df["snapshot_content"].notna()]

        files_dir = self.path_to_format(fb.CompositeFormat.FILES)
        files_dir.mkdir(parents=True, exist_ok=True)

        for _, row in snapshots_df.iterrows():
            org = row["org"]
            url = row["url"]
            year = int(row["year"])
            snapshot_content = row["snapshot_content"]

            url_escaped = urllib.parse.quote(url, safe="")

            snapshot_dir = files_dir / org / url_escaped / str(year)
            snapshot_dir.mkdir(parents=True, exist_ok=True)

            snapshot_path = snapshot_dir / "snapshot.html"
            with open(snapshot_path, "w", encoding="utf-8") as f:
                f.write(snapshot_content)


class WMSnapshotContentLLMRequestGroup(SQLModel, table=True):
    __tablename__ = "wm_snapshot_content_llm_request_groups"
    __table_args__ = {"extend_existing": True}

    llm_request_group_id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_by_class: str


class WMSnapshotContentLLMRequestExtra(SQLModel, table=True):
    __tablename__ = "wm_snapshot_content_llm_request_extra"
    __table_args__ = {"extend_existing": True}

    llm_request_extra_id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    org: str
    url: str
    year: int
    snapshot_url: str


class GPUInventoryItem(pyd.BaseModel):
    """GPU inventory item for a compute cluster."""

    model: str = pyd.Field(
        description="GPU model name, e.g. NVIDIA A100",
    )
    count: Optional[int] = pyd.Field(
        description="Total number of GPUs of this model in the cluster",
    )
    memory_gb: Optional[float] = pyd.Field(
        description="Per-GPU memory if stated (e.g., 40, 80)",
    )


class WMExtractedClusterSpecs(pyd.BaseModel):
    """Structured schema for compute cluster specifications extraction."""

    cluster_name: str = pyd.Field(
        description="The nickname or formal name of the compute cluster",
    )
    initial_deployment_date: Optional[str] = pyd.Field(
        description="The date when the cluster was initially deployed (e.g., '2015', '2015-03', '2015-03-15')",
    )
    cpus_total: Optional[int] = pyd.Field(
        description="The total number of CPUs in the cluster",
    )
    cores_total: Optional[int] = pyd.Field(
        description="The total number of CPU cores in the cluster",
    )
    gpus_total: Optional[int] = pyd.Field(
        description="The total number of GPUs in the cluster",
    )
    gpus: Optional[List[GPUInventoryItem]] = pyd.Field(
        default=None,
        description="List of GPU models present in the cluster with counts",
    )
    nodes_total: Optional[int] = pyd.Field(
        description="The total number of compute nodes in the cluster",
    )
    memory_total_gb: Optional[int] = pyd.Field(
        description="The total memory available in the cluster, in gigabytes",
    )
    storage_total_tb: Optional[int] = pyd.Field(
        description="The total storage available in the cluster, in terabytes",
    )
    tflops_total: Optional[float] = pyd.Field(
        description="The total computational performance of the cluster, in TFLOPS",
    )
    price_tiers: Optional[str] = pyd.Field(
        description="Description of price tiers for cluster usage (e.g., 'Free for all users', 'Free for researchers, $0.05/core-hour for others')",
    )
    free_to_use: Optional[bool] = pyd.Field(
        description="Is the cluster free to use inside the org or some cash payment/compensation is required.",
    )
    scheduler_main: Optional[str] = pyd.Field(
        description="The main scheduler used for jobs in the cluster (such as Slurm, PBS, IBM LSF, etc.)",
    )
    software_installed: Optional[str] = pyd.Field(
        description="List of major software packages installed on the cluster (e.g., 'MATLAB, Python, R, CUDA, TensorFlow')",
    )


class WMSnapshotContentLLMExtractionDB(fb.LLMRequestsDBMixin, fb.HTTPRequestsDBMixin, fb.DBDataObject):
    """Database for LLM requests with structured output extraction from snapshot content."""

    id: str = "wm_snapshot_content_llm_extraction_db"
    description: str = "Database for logging and executing LLM extraction requests for cluster specs from snapshot content"
    schema: List[Any] = [
        WMSnapshotContentLLMRequestGroup,
        WMSnapshotContentLLMRequestExtra,
        fb.LLMRequest,
        WMSnapshotContentHTTPRequestGroup,
        WMSnapshotContentHTTPRequestExtra,
        fb.HTTPRequest,
    ]
    supported_versions = tuple(URLVersions)

    async def _populate_llm_requests(self) -> uuid.UUID:
        """Populate database with LLM cluster specs extraction requests."""
        llm_requests = await self._extract_cluster_specs(
            snapshot_version=self.version,
            model=fb.LLMModels.GEMINI_2_5_FLASH_LITE,
        )
        return llm_requests[0].llm_request_group_id if llm_requests else None

    async def _extract_cluster_specs(
        self,
        snapshot_version: Enum,
        model: fb.LLMModels = fb.LLMModels.GPT_5,
    ) -> List[fb.LLMRequest]:
        """Extract cluster specifications from snapshot content using structured output."""
        from p40_flowbase.helpers import render_prompt_template

        snapshot_obj = WMSnapshotContent(version=snapshot_version)

        if not snapshot_obj.path_to_format(fb.TableFormat.PARQUET).exists():
            snapshot_obj.make(replace=False)

        snapshots_df = snapshot_obj.pdf

        snapshots_df = snapshots_df[snapshots_df["snapshot_content"].notna()]

        group = WMSnapshotContentLLMRequestGroup(
            created_by_class=self.__class__.__name__,
        )

        async with self.session_factory() as session:
            session.add(group)
            await session.commit()
            await session.refresh(group)

        system_prompt = render_prompt_template(
            template_name="web_archive_cluster_extraction.md.jinja",
            project_package="web_archive.prompts",
        )

        llm_requests_data = []

        for _, row in snapshots_df.iterrows():
            org = row["org"]
            url = row["url"]
            year = int(row["year"])
            snapshot_url = row["snapshot_url"]
            snapshot_content = row["snapshot_content"]

            extra = WMSnapshotContentLLMRequestExtra(
                org=org,
                url=url,
                year=year,
                snapshot_url=snapshot_url,
            )

            async with self.session_factory() as session:
                session.add(extra)
                await session.commit()
                await session.refresh(extra)

            user_prompt = (
                f"Extract compute cluster specifications from this webpage snapshot "
                f"from {org} (year {year}):\n"
                f"<webpage_snapshot>\n"
                f"{snapshot_content}\n"
                f"</webpage_snapshot>\n"
            )

            llm_requests_data.append({
                "model": model,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "temperature": 0.1,
                "response_schema": WMExtractedClusterSpecs,
                "llm_request_group_id": group.llm_request_group_id,
                "llm_request_extra_id": extra.llm_request_extra_id,
            })

        llm_requests = await self._add_llm_requests(llm_requests_data)

        return llm_requests


class ClusterSpecsStruct(pyd.BaseModel):
    org: str = pyd.Field(
        title="Organization",
        description="Organization identifier",
        json_schema_extra={"units": "text"},
    )
    url: str = pyd.Field(
        title="URL",
        description="Source URL",
        json_schema_extra={"units": "text"},
    )
    year: int = pyd.Field(
        title="Year",
        description="Snapshot year",
        json_schema_extra={"units": "year"},
    )
    snapshot_url: str = pyd.Field(
        title="Snapshot URL",
        description="Wayback Machine snapshot URL",
        json_schema_extra={"units": "text"},
    )
    cluster_name: Optional[str] = pyd.Field(
        title="Cluster Name",
        description="Name of the compute cluster",
        json_schema_extra={"units": "text"},
    )
    initial_deployment_date: Optional[str] = pyd.Field(
        title="Initial Deployment Date",
        description="Date when the cluster was initially deployed",
        json_schema_extra={"units": "text"},
    )
    cpus_total: Optional[int] = pyd.Field(
        title="Total CPUs",
        description="Total number of CPUs",
        json_schema_extra={"units": "count"},
    )
    cores_total: Optional[int] = pyd.Field(
        title="Total Cores",
        description="Total number of CPU cores",
        json_schema_extra={"units": "count"},
    )
    gpus_total: Optional[int] = pyd.Field(
        title="Total GPUs",
        description="Total number of GPUs",
        json_schema_extra={"units": "count"},
    )
    gpus: Optional[str] = pyd.Field(
        title="GPU Inventory",
        description="JSON list of GPU models with counts and memory",
        json_schema_extra={"units": "json"},
    )
    nodes_total: Optional[int] = pyd.Field(
        title="Total Nodes",
        description="Total number of compute nodes",
        json_schema_extra={"units": "count"},
    )
    memory_total_gb: Optional[int] = pyd.Field(
        title="Total Memory (GB)",
        description="Total memory in gigabytes",
        json_schema_extra={"units": "GB"},
    )
    storage_total_tb: Optional[int] = pyd.Field(
        title="Total Storage (TB)",
        description="Total storage in terabytes",
        json_schema_extra={"units": "TB"},
    )
    tflops_total: Optional[float] = pyd.Field(
        title="Total TFLOPS",
        description="Total computational performance in TFLOPS",
        json_schema_extra={"units": "TFLOPS"},
    )
    price_tiers: Optional[str] = pyd.Field(
        title="Price Tiers",
        description="Price tiers for cluster usage",
        json_schema_extra={"units": "text"},
    )
    free_to_use: Optional[bool] = pyd.Field(
        title="Free to Use",
        description="Whether the cluster is free to use",
        json_schema_extra={"units": "boolean"},
    )
    scheduler_main: Optional[str] = pyd.Field(
        title="Main Scheduler",
        description="Main job scheduler",
        json_schema_extra={"units": "text"},
    )
    software_installed: Optional[str] = pyd.Field(
        title="Software Installed",
        description="Major software packages installed on the cluster",
        json_schema_extra={"units": "text"},
    )


class ClusterSpecs(fb.TableDataObject):
    id: str = "cluster_specs"
    description: str = "Extracted compute cluster specifications from archived webpages"
    supported_versions = tuple(URLVersions)
    schema = ClusterSpecsStruct

    def _make_default(self):
        """Extract cluster specs from LLM extraction results."""
        import asyncio

        asyncio.run(self._extract_from_db())

    async def _extract_from_db(self):
        """Extract cluster specs from LLM extraction database."""
        from sqlmodel import select

        db = WMSnapshotContentLLMExtractionDB(version=self.version)

        if not db.path_to_format(fb.DBFormat.SQLITE).exists():
            await db.make_async()

        async with db.session_factory() as session:
            statement = (
                select(fb.LLMRequest, WMSnapshotContentLLMRequestExtra)
                .join(
                    WMSnapshotContentLLMRequestExtra,
                    fb.LLMRequest.llm_request_extra_id == WMSnapshotContentLLMRequestExtra.llm_request_extra_id,
                )
                .where(
                    fb.LLMRequest.requested_at_utc.is_not(None),
                    fb.LLMRequest.response_text.is_not(None),
                )
                .order_by(fb.LLMRequest.requested_at_utc.desc())
            )
            result = await session.exec(statement)
            rows = result.all()

        records = []
        seen_keys = set()

        for llm_request, extra in rows:
            key = (extra.org, extra.url, extra.year, extra.snapshot_url)

            if key in seen_keys:
                continue

            seen_keys.add(key)

            try:
                cluster_specs = json.loads(llm_request.response_text)

                gpus_raw = cluster_specs.get("gpus")
                gpus_json = json.dumps(gpus_raw) if gpus_raw else None

                records.append({
                    "org": extra.org,
                    "url": extra.url,
                    "year": extra.year,
                    "snapshot_url": extra.snapshot_url,
                    "cluster_name": cluster_specs.get("cluster_name"),
                    "initial_deployment_date": cluster_specs.get("initial_deployment_date"),
                    "cpus_total": cluster_specs.get("cpus_total"),
                    "cores_total": cluster_specs.get("cores_total"),
                    "gpus_total": cluster_specs.get("gpus_total"),
                    "gpus": gpus_json,
                    "nodes_total": cluster_specs.get("nodes_total"),
                    "memory_total_gb": cluster_specs.get("memory_total_gb"),
                    "storage_total_tb": cluster_specs.get("storage_total_tb"),
                    "tflops_total": cluster_specs.get("tflops_total"),
                    "price_tiers": cluster_specs.get("price_tiers"),
                    "free_to_use": cluster_specs.get("free_to_use"),
                    "scheduler_main": cluster_specs.get("scheduler_main"),
                    "software_installed": cluster_specs.get("software_installed"),
                })
            except (json.JSONDecodeError, KeyError):
                continue

        df = pd.DataFrame(records)
        df = df.convert_dtypes(dtype_backend="pyarrow")
        df.to_parquet(self.path_to_format(fb.TableFormat.PARQUET), index=False)

        await db.close()


# =============================================================================
# Agentic Extraction Pipeline (alternative to LLM extraction)
# =============================================================================


class WMSnapshotAgentExtractionGroup(SQLModel, table=True):
    """Group of related agent extraction tasks."""

    __tablename__ = "wm_snapshot_agent_extraction_groups"
    __table_args__ = {"extend_existing": True}

    agent_task_group_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
    )
    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_by_class: str
    model_used: str


class WMSnapshotAgentExtractionExtra(SQLModel, table=True):
    """Per-task metadata linking agent task to snapshot file."""

    __tablename__ = "wm_snapshot_agent_extraction_extra"
    __table_args__ = {"extend_existing": True}

    agent_task_extra_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
    )
    org: str
    url: str
    year: int
    snapshot_url: str
    snapshot_path: str


class WMSnapshotAgentExtractionDB(fb.AgentTasksDBMixin, fb.DBDataObject):
    """Database for agent-based cluster specs extraction from snapshot content.

    Uses Claude Agent SDK with full tool access (Read, WebSearch, WebFetch, etc.)
    to extract cluster specifications from archived HTML files.
    """

    id: str = "wm_snapshot_agent_extraction_db"
    description: str = (
        "Database for agentic extraction of cluster specs using Claude Agent SDK"
    )
    supported_versions = tuple(URLVersions)
    schema: List[Any] = [
        WMSnapshotAgentExtractionGroup,
        WMSnapshotAgentExtractionExtra,
        fb.AgentTask,
        fb.AgentToolCall,
        fb.AgentMessage,
        fb.AgentFile,
    ]

    async def _populate_agent_tasks(self) -> uuid.UUID:
        """Populate database with agent extraction tasks for each snapshot file."""
        import urllib.parse

        from p40_flowbase.helpers import render_prompt_template

        snapshot_files_obj = WMSnapshotFiles(version=self.version)
        if not snapshot_files_obj.path_to_format(fb.CompositeFormat.FILES).exists():
            snapshot_files_obj.make(replace=False)

        files_dir = snapshot_files_obj.path_to_format(fb.CompositeFormat.FILES)

        snapshot_content_obj = WMSnapshotContent(version=self.version)
        if not snapshot_content_obj.path_to_format(fb.TableFormat.PARQUET).exists():
            snapshot_content_obj.make(replace=False)
        content_df = snapshot_content_obj.pdf

        snapshot_url_lookup = {}
        for _, row in content_df.iterrows():
            key = (row["org"], row["url"], int(row["year"]))
            snapshot_url_lookup[key] = row["snapshot_url"]

        group = WMSnapshotAgentExtractionGroup(
            created_by_class=self.__class__.__name__,
            model_used=fb.AgentModels.CLAUDE_OPUS_4_5.value.id,
        )

        async with self.session_factory() as session:
            session.add(group)
            await session.commit()
            await session.refresh(group)

        system_prompt = render_prompt_template(
            template_name="agent_cluster_extraction.md.jinja",
            project_package="web_archive.prompts",
        )

        agent_tasks_data = []

        for org_dir in files_dir.iterdir():
            if not org_dir.is_dir():
                continue
            org = org_dir.name

            for url_dir in org_dir.iterdir():
                if not url_dir.is_dir():
                    continue
                url = urllib.parse.unquote(url_dir.name)

                for year_dir in url_dir.iterdir():
                    if not year_dir.is_dir():
                        continue
                    year = int(year_dir.name)

                    snapshot_path = year_dir / "snapshot.html"
                    if not snapshot_path.exists():
                        continue

                    snapshot_url = snapshot_url_lookup.get((org, url, year), "")

                    extra = WMSnapshotAgentExtractionExtra(
                        org=org,
                        url=url,
                        year=year,
                        snapshot_url=snapshot_url,
                        snapshot_path=str(snapshot_path.absolute()),
                    )

                    async with self.session_factory() as session:
                        session.add(extra)
                        await session.commit()
                        await session.refresh(extra)

                    task_prompt = (
                        f"Extract compute cluster specifications from the HTML file at:\n"
                        f"{snapshot_path.absolute()}\n\n"
                        f"Organization: {org}\n"
                        f"Snapshot year: {year}\n"
                        f"Original URL: {url}\n\n"
                        f"Read the file and extract all cluster specifications. "
                        f"If specs are ambiguous, use WebSearch for context."
                    )

                    agent_tasks_data.append({
                        "model": fb.AgentModels.CLAUDE_OPUS_4_5,
                        "task_prompt": task_prompt,
                        "system_prompt": system_prompt,
                        "max_turns": 10,
                        "working_directory": str(files_dir),
                        "output_format": WMExtractedClusterSpecs,
                        "agent_task_group_id": group.agent_task_group_id,
                        "agent_task_extra_id": extra.agent_task_extra_id,
                    })

        await self._add_agent_tasks(agent_tasks_data)

        return group.agent_task_group_id


class AgentClusterSpecsStruct(pyd.BaseModel):
    """Schema for agent-extracted cluster specifications with agent metadata."""

    org: str = pyd.Field(
        title="Organization",
        description="Organization identifier",
        json_schema_extra={"units": "text"},
    )
    url: str = pyd.Field(
        title="URL",
        description="Source URL",
        json_schema_extra={"units": "text"},
    )
    year: int = pyd.Field(
        title="Year",
        description="Snapshot year",
        json_schema_extra={"units": "year"},
    )
    snapshot_url: str = pyd.Field(
        title="Snapshot URL",
        description="Wayback Machine URL of the archived snapshot",
        json_schema_extra={"units": "text"},
    )
    cluster_name: Optional[str] = pyd.Field(
        default=None,
        title="Cluster Name",
        description="Name of the compute cluster",
        json_schema_extra={"units": "text"},
    )
    initial_deployment_date: Optional[str] = pyd.Field(
        default=None,
        title="Initial Deployment Date",
        description="Date when the cluster was initially deployed",
        json_schema_extra={"units": "text"},
    )
    cpus_total: Optional[int] = pyd.Field(
        default=None,
        title="Total CPUs",
        description="Total number of CPUs",
        json_schema_extra={"units": "count"},
    )
    cores_total: Optional[int] = pyd.Field(
        default=None,
        title="Total Cores",
        description="Total number of CPU cores",
        json_schema_extra={"units": "count"},
    )
    gpus_total: Optional[int] = pyd.Field(
        default=None,
        title="Total GPUs",
        description="Total number of GPUs",
        json_schema_extra={"units": "count"},
    )
    gpus: Optional[str] = pyd.Field(
        default=None,
        title="GPU Inventory",
        description="JSON list of GPU models with counts and memory",
        json_schema_extra={"units": "json"},
    )
    nodes_total: Optional[int] = pyd.Field(
        default=None,
        title="Total Nodes",
        description="Total number of compute nodes",
        json_schema_extra={"units": "count"},
    )
    memory_total_gb: Optional[int] = pyd.Field(
        default=None,
        title="Total Memory (GB)",
        description="Total memory in gigabytes",
        json_schema_extra={"units": "GB"},
    )
    storage_total_tb: Optional[int] = pyd.Field(
        default=None,
        title="Total Storage (TB)",
        description="Total storage in terabytes",
        json_schema_extra={"units": "TB"},
    )
    tflops_total: Optional[float] = pyd.Field(
        default=None,
        title="Total TFLOPS",
        description="Total computational performance in TFLOPS",
        json_schema_extra={"units": "TFLOPS"},
    )
    price_tiers: Optional[str] = pyd.Field(
        default=None,
        title="Price Tiers",
        description="Price tiers for cluster usage",
        json_schema_extra={"units": "text"},
    )
    free_to_use: Optional[bool] = pyd.Field(
        default=None,
        title="Free to Use",
        description="Whether the cluster is free to use",
        json_schema_extra={"units": "boolean"},
    )
    scheduler_main: Optional[str] = pyd.Field(
        default=None,
        title="Main Scheduler",
        description="Main job scheduler",
        json_schema_extra={"units": "text"},
    )
    software_installed: Optional[str] = pyd.Field(
        default=None,
        title="Software Installed",
        description="Major software packages installed on the cluster",
        json_schema_extra={"units": "text"},
    )
    agent_num_turns: Optional[int] = pyd.Field(
        default=None,
        title="Agent Turns",
        description="Number of conversation turns used by the agent",
        json_schema_extra={"units": "count"},
    )
    agent_cost_usd: Optional[float] = pyd.Field(
        default=None,
        title="Agent Cost (USD)",
        description="Total API cost for the agent task",
        json_schema_extra={"units": "USD"},
    )
    agent_tools_used: Optional[str] = pyd.Field(
        default=None,
        title="Agent Tools Used",
        description="JSON list of tool names used by the agent",
        json_schema_extra={"units": "json"},
    )


class AgentClusterSpecs(fb.TableDataObject):
    """Extracted cluster specs from agent-based extraction."""

    id: str = "agent_cluster_specs"
    description: str = "Cluster specifications extracted via agentic multi-turn extraction"
    supported_versions = tuple(URLVersions)
    schema = AgentClusterSpecsStruct

    def _make_default(self):
        """Extract cluster specs from agent extraction results."""
        import asyncio

        asyncio.run(self._extract_from_db())

    async def _extract_from_db(self):
        """Extract cluster specs from agent extraction database."""
        from sqlmodel import select

        db = WMSnapshotAgentExtractionDB(version=self.version)

        if not db.path_to_format(fb.DBFormat.SQLITE).exists():
            await db.make_async()

        async with db.session_factory() as session:
            statement = (
                select(fb.AgentTask, WMSnapshotAgentExtractionExtra)
                .join(
                    WMSnapshotAgentExtractionExtra,
                    fb.AgentTask.agent_task_extra_id
                    == WMSnapshotAgentExtractionExtra.agent_task_extra_id,
                )
                .where(
                    fb.AgentTask.completed_at_utc.is_not(None),
                    fb.AgentTask.is_error == False,
                    fb.AgentTask.final_response.is_not(None),
                )
                .order_by(fb.AgentTask.completed_at_utc.desc())
            )
            result = await session.exec(statement)
            rows = result.all()

        async with db.session_factory() as session:
            tool_calls_statement = select(fb.AgentToolCall)
            tool_calls_result = await session.exec(tool_calls_statement)
            all_tool_calls = tool_calls_result.all()

        tools_by_task = {}
        for tc in all_tool_calls:
            task_id = tc.agent_task_id
            if task_id not in tools_by_task:
                tools_by_task[task_id] = set()
            tools_by_task[task_id].add(tc.tool_name)

        records = []
        seen_keys = set()

        for agent_task, extra in rows:
            key = (extra.org, extra.url, extra.year)

            if key in seen_keys:
                continue
            seen_keys.add(key)

            try:
                cluster_specs = self._extract_json_from_response(
                    agent_task.final_response
                )

                if cluster_specs is None:
                    continue

                gpus_raw = cluster_specs.get("gpus")
                gpus_json = json.dumps(gpus_raw) if gpus_raw else None

                task_tools = list(tools_by_task.get(agent_task.agent_task_id, []))

                records.append({
                    "org": extra.org,
                    "url": extra.url,
                    "year": extra.year,
                    "snapshot_url": extra.snapshot_url,
                    "cluster_name": cluster_specs.get("cluster_name"),
                    "initial_deployment_date": cluster_specs.get(
                        "initial_deployment_date"
                    ),
                    "cpus_total": cluster_specs.get("cpus_total"),
                    "cores_total": cluster_specs.get("cores_total"),
                    "gpus_total": cluster_specs.get("gpus_total"),
                    "gpus": gpus_json,
                    "nodes_total": cluster_specs.get("nodes_total"),
                    "memory_total_gb": cluster_specs.get("memory_total_gb"),
                    "storage_total_tb": cluster_specs.get("storage_total_tb"),
                    "tflops_total": cluster_specs.get("tflops_total"),
                    "price_tiers": cluster_specs.get("price_tiers"),
                    "free_to_use": cluster_specs.get("free_to_use"),
                    "scheduler_main": cluster_specs.get("scheduler_main"),
                    "software_installed": cluster_specs.get("software_installed"),
                    "agent_num_turns": agent_task.num_turns,
                    "agent_cost_usd": agent_task.total_cost_usd,
                    "agent_tools_used": json.dumps(task_tools),
                })
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

        df = pd.DataFrame(records)
        df = df.convert_dtypes(dtype_backend="pyarrow")
        df.to_parquet(self.path_to_format(fb.TableFormat.PARQUET), index=False)

        await db.close()

    def _extract_json_from_response(self, response_text: str) -> Optional[dict]:
        """Extract JSON object from agent response text.

        Handles various response formats including:
        - Pure JSON
        - JSON wrapped in markdown code blocks
        - JSON embedded in natural language
        """
        if not response_text:
            return None

        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            pass

        code_block_match = re.search(
            r"```(?:json)?\s*\n?(.*?)\n?```",
            response_text,
            re.DOTALL,
        )
        if code_block_match:
            try:
                return json.loads(code_block_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        json_match = re.search(
            r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}",
            response_text,
            re.DOTALL,
        )
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        return None
