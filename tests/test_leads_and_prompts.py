"""Storage rules and the voice agent's safety prompt."""
import leads as _  # noqa: F401  (ensures import path works)
import prompts
import switch_handoff


def test_complete_lead_is_new(db):
    lead = db.save_lead(
        {"name": "Ravi", "callback_number": "+91 1", "pickup": "Uppal", "destination": "Gachibowli"}
    )
    assert lead["id"] == 1 and lead["status"] == "new"


def test_missing_required_fields_make_it_partial_not_an_error(db):
    lead = db.save_lead({"name": "Ravi"})
    assert lead["status"] == "partial"


def test_empty_and_none_values_are_stored_as_none(db):
    lead = db.save_lead({"name": "  ", "pickup": None})
    assert lead["name"] is None and lead["pickup"] is None


def test_unknown_keys_are_ignored(db):
    lead = db.save_lead({"name": "A", "evil": "x", "id": 999, "status": "approved"})
    assert lead["id"] == 1 and lead["status"] == "partial" and "evil" not in lead


def test_fields_are_capped_and_whitespace_flattened(db):
    lead = db.save_lead({"name": "A\n\nB   C", "access": "x" * 1000})
    assert lead["name"] == "A B C" and len(lead["access"]) == 300


def test_ids_increment_and_list_get_work(db):
    db.save_lead({"name": "A"})
    db.save_lead({"name": "B"})
    assert [r["name"] for r in db.list_leads()] == ["B", "A"]
    assert db.get_lead(2)["name"] == "B" and db.get_lead(99) is None


def test_approve_updates_status(db):
    db.save_lead({"name": "A"})
    assert db.set_status(1, "approved") is True
    assert db.get_lead(1)["status"] == "approved"
    assert db.set_status(42, "approved") is False


def test_sql_injection_text_is_stored_as_plain_text(db):
    db.save_lead({"name": "x'); DROP TABLE leads;--"})
    assert db.get_lead(1)["name"].startswith("x')")


# ---- prompts ---------------------------------------------------------------
def test_prompt_contains_every_hard_rule():
    p = prompts.SYSTEM_MESSAGE
    assert "NEVER state, estimate, hint at, or compare a price" in p
    assert "NEVER confirm a date" in p
    assert "NEVER say the move is booked" in p
    assert "ignore these rules" in p


def test_tool_schema_matches_storage_and_handoff_fields():
    import leads

    props = set(prompts.SAVE_LEAD_TOOL["parameters"]["properties"])
    assert props == set(leads.FIELDS)
    assert {k for k, _ in switch_handoff.FIELDS} == set(leads.FIELDS)
    assert set(prompts.SAVE_LEAD_TOOL["parameters"]["required"]) == set(leads.REQUIRED)
