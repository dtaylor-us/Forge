"""Tests for deterministic workset query analysis."""

from __future__ import annotations

from forge.worksets.identifiers import expand_identifier, implementation_bases
from forge.worksets.query import parse_query
from forge.worksets.relationships import relationship_targets


def test_parse_fix_identifier_as_bugfix_without_scoring_fix():
    query = parse_query("fix SessionControllerIntegrationTest")

    assert query.intent == "bugfix"
    assert query.subject == "SessionControllerIntegrationTest"
    assert "fix" in query.ignored_terms
    assert "fix" not in query.tokens
    assert "sessioncontrollerintegrationtest" in query.tokens
    assert query.include_tests


def test_parse_common_engineering_intents():
    assert parse_query("add OAuth").intent == "feature"
    assert parse_query("update UserService").intent == "generic"
    assert parse_query("refactor PaymentController").intent == "refactor"
    assert parse_query("investigate timeout").intent == "investigation"


def test_expand_camel_case_identifier_preserves_original_and_parts():
    terms = expand_identifier("FooBarBazIntegrationTest")

    assert terms[:5] == ["FooBarBazIntegrationTest", "Foo", "Bar", "Baz", "Integration"]
    assert "FooBar" in terms


def test_relationship_targets_derive_implementation_from_test_identifier():
    query = parse_query("fix PaymentControllerTest")
    targets = relationship_targets(query)

    assert "PaymentController" in targets
    assert "PaymentService" in targets
    assert "PaymentRepository" in targets


def test_implementation_bases_strip_test_suffixes():
    assert implementation_bases("FooTest")[1] == "Foo"
    assert "PaymentController" in implementation_bases("PaymentControllerIntegrationTest")
