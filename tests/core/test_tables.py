"""Tests for the SQLModel Group/Extra table factories."""

import uuid
from datetime import datetime

from sqlmodel import SQLModel

from p40_flowbase.core.tables import (
    make_agent_task_extra_table,
    make_agent_task_group_table,
    make_http_request_extra_table,
    make_http_request_group_table,
    make_llm_request_extra_table,
    make_llm_request_group_table,
)


class TestHTTPRequestGroupFactory:
    def test_class_name_is_camelcased(self):
        Cls = make_http_request_group_table(prefix="my_prefix")
        assert Cls.__name__ == "MyPrefixHTTPRequestGroup"

    def test_tablename_from_prefix(self):
        Cls = make_http_request_group_table(prefix="my_prefix")
        assert Cls.__tablename__ == "my_prefix_http_request_groups"  # pyright: ignore[reportGeneralTypeIssues]

    def test_base_columns_present(self):
        Cls = make_http_request_group_table(prefix="foo")
        annotations = Cls.__annotations__
        assert "http_request_group_id" in annotations
        assert "created_at_utc" in annotations
        assert "created_by_class" in annotations

    def test_primary_key_is_http_request_group_id(self):
        Cls = make_http_request_group_table(prefix="foo")
        pk_cols = [c.name for c in Cls.__table__.primary_key.columns]  # pyright: ignore[reportAttributeAccessIssue]
        assert pk_cols == ["http_request_group_id"]

    def test_extra_columns_added(self):
        Cls = make_http_request_group_table(
            prefix="foo",
            lane_id=str,
            step_index=int,
        )
        annotations = Cls.__annotations__
        assert annotations["lane_id"] is str
        assert annotations["step_index"] is int

    def test_instantiation_defaults_primary_key_and_timestamp(self):
        Cls = make_http_request_group_table(
            prefix="inst_test",
            extra_col=(str, "default_val"),
        )
        instance = Cls(created_by_class="TestClass")
        assert isinstance(instance.http_request_group_id, uuid.UUID)
        assert isinstance(instance.created_at_utc, datetime)
        assert instance.created_by_class == "TestClass"
        assert instance.extra_col == "default_val"

    def test_is_sqlmodel_subclass(self):
        Cls = make_http_request_group_table(prefix="is_sqlmodel")
        assert issubclass(Cls, SQLModel)


class TestHTTPRequestExtraFactory:
    def test_tablename_and_class_name(self):
        Cls = make_http_request_extra_table(prefix="rc_page_search")
        assert Cls.__name__ == "RcPageSearchHTTPRequestExtra"
        assert Cls.__tablename__ == "rc_page_search_http_request_extra"  # pyright: ignore[reportGeneralTypeIssues]

    def test_primary_key(self):
        Cls = make_http_request_extra_table(prefix="foo")
        pk_cols = [c.name for c in Cls.__table__.primary_key.columns]  # pyright: ignore[reportAttributeAccessIssue]
        assert pk_cols == ["http_request_extra_id"]

    def test_extra_columns_with_defaults(self):
        Cls = make_http_request_extra_table(
            prefix="foo",
            url=str,
            attempt=(int, 0),
        )
        instance = Cls(url="http://example.com")
        assert instance.url == "http://example.com"
        assert instance.attempt == 0


class TestLLMRequestGroupFactory:
    def test_tablename_and_class_name(self):
        Cls = make_llm_request_group_table(prefix="llm_test")
        assert Cls.__name__ == "LlmTestLLMRequestGroup"
        assert Cls.__tablename__ == "llm_test_llm_request_groups"  # pyright: ignore[reportGeneralTypeIssues]

    def test_primary_key_is_llm_request_group_id(self):
        Cls = make_llm_request_group_table(prefix="foo")
        pk_cols = [c.name for c in Cls.__table__.primary_key.columns]  # pyright: ignore[reportAttributeAccessIssue]
        assert pk_cols == ["llm_request_group_id"]


class TestLLMRequestExtraFactory:
    def test_tablename_and_class_name(self):
        Cls = make_llm_request_extra_table(prefix="llm_extra")
        assert Cls.__name__ == "LlmExtraLLMRequestExtra"
        assert Cls.__tablename__ == "llm_extra_llm_request_extra"  # pyright: ignore[reportGeneralTypeIssues]

    def test_primary_key(self):
        Cls = make_llm_request_extra_table(prefix="foo")
        pk_cols = [c.name for c in Cls.__table__.primary_key.columns]  # pyright: ignore[reportAttributeAccessIssue]
        assert pk_cols == ["llm_request_extra_id"]


class TestAgentTaskGroupFactory:
    def test_tablename_and_class_name(self):
        Cls = make_agent_task_group_table(prefix="agents_test")
        assert Cls.__name__ == "AgentsTestAgentTaskGroup"
        assert Cls.__tablename__ == "agents_test_agent_task_groups"  # pyright: ignore[reportGeneralTypeIssues]

    def test_primary_key_is_agent_task_group_id(self):
        Cls = make_agent_task_group_table(prefix="foo")
        pk_cols = [c.name for c in Cls.__table__.primary_key.columns]  # pyright: ignore[reportAttributeAccessIssue]
        assert pk_cols == ["agent_task_group_id"]


class TestAgentTaskExtraFactory:
    def test_tablename_and_class_name(self):
        Cls = make_agent_task_extra_table(prefix="agents_extra")
        assert Cls.__name__ == "AgentsExtraAgentTaskExtra"
        assert Cls.__tablename__ == "agents_extra_agent_task_extra"  # pyright: ignore[reportGeneralTypeIssues]

    def test_primary_key(self):
        Cls = make_agent_task_extra_table(prefix="foo")
        pk_cols = [c.name for c in Cls.__table__.primary_key.columns]  # pyright: ignore[reportAttributeAccessIssue]
        assert pk_cols == ["agent_task_extra_id"]


class TestDistinctPrefixesYieldDistinctTables:
    def test_same_prefix_reuses_table(self):
        first = make_http_request_group_table(prefix="dup_check")
        second = make_http_request_group_table(prefix="dup_check")
        assert first.__tablename__ == second.__tablename__  # pyright: ignore[reportGeneralTypeIssues]

    def test_different_prefixes_yield_different_tables(self):
        a = make_http_request_group_table(prefix="prefix_a")
        b = make_http_request_group_table(prefix="prefix_b")
        assert a.__tablename__ != b.__tablename__  # pyright: ignore[reportGeneralTypeIssues]
        assert a.__name__ != b.__name__
