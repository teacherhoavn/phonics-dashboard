"""Data access for the phonics dashboard.

Everything the UI needs from storage lives here as a named function, so
app.py never builds a query itself. That buys two things:

  * the Supabase schema can change without touching the UI, and
  * a second backend can satisfy the same contract -- which is what
    local_backend.py does, letting the whole app be reviewed offline
    before the teacher's real Supabase project exists.

SupabaseBackend is the real one and the only one used in production; it is
selected whenever SUPABASE_URL / SUPABASE_KEY are configured.
"""

from __future__ import annotations

import os
from datetime import date

import streamlit as st
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))


def get_setting(key: str):
    """Streamlit Cloud secrets first, then .env -- same pattern as deploy docs."""
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.environ.get(key)


SUPABASE_URL = get_setting("SUPABASE_URL")
SUPABASE_KEY = get_setting("SUPABASE_KEY")

# Set PHONICS_DEMO=1 to force the offline SQLite backend even if Supabase
# credentials happen to be present. Without credentials it is the fallback.
DEMO_MODE = str(get_setting("PHONICS_DEMO") or "").strip() in ("1", "true", "yes")
USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_KEY) and not DEMO_MODE

def roster_order(students: list) -> list:
    """Her register order, with unnumbered students last and ties by name."""
    return sorted(
        students,
        key=lambda s: (s.get("order_index") is None, s.get("order_index") or 0, s["name"]),
    )


CHECKIN_FIELDS = [
    "blending_rating",
    "segmenting_rating",
    "letter_formation_rating",
    "pencil_grip_rating",
    "tricky_words_rating",
    "participation_rating",
]


# ---------------------------------------------------------------------------
# Supabase backend
# ---------------------------------------------------------------------------

class SupabaseBackend:
    """Thin wrapper over an authenticated supabase-py client."""

    is_demo = False

    def __init__(self, client):
        self.client = client

    # -- roster ------------------------------------------------------------

    def list_classes(self, include_archived: bool = False) -> list:
        q = self.client.table("classes").select("*").order("created_at")
        if not include_archived:
            q = q.eq("archived", False)
        return roster_order(q.execute().data)

    def add_class(self, name: str, level: str = None):
        self.client.table("classes").insert(
            {"name": name, "level": level or None}
        ).execute()

    def set_class_archived(self, class_id: str, archived: bool):
        self.client.table("classes").update({"archived": archived}).eq(
            "id", class_id
        ).execute()

    def update_class(self, class_id: str, fields: dict):
        if fields:
            self.client.table("classes").update(fields).eq("id", class_id).execute()

    def delete_class(self, class_id: str):
        """Permanent, and refused while the class still has students.

        The UI disables the button in that case, but the check lives here
        too: a class deleted by accident would take every test and check-in
        belonging to its students, and none of that can be recovered.
        """
        if self.list_students(class_id=class_id, include_archived=True):
            raise ValueError("That class still has students.")
        self.client.table("classes").delete().eq("id", class_id).execute()

    def list_students(self, class_id: str = None, include_archived: bool = False) -> list:
        q = self.client.table("students").select("*, classes(id, name)")
        if class_id:
            q = q.eq("class_id", class_id)
        if not include_archived:
            q = q.eq("archived", False)
        return roster_order(q.execute().data)

    def add_student(self, class_id: str, name: str, parent_contact: str = None,
                    photo_b64: str = None, parent_name: str = None,
                    order_index: int = None):
        self.client.table("students").insert(
            {
                "class_id": class_id,
                "name": name,
                "parent_name": parent_name or None,
                "order_index": order_index,
                "parent_contact": parent_contact or None,
                "photo_b64": photo_b64,
            }
        ).execute()

    def update_student(self, student_id: str, fields: dict):
        self.client.table("students").update(fields).eq("id", student_id).execute()

    def set_student_archived(self, student_id: str, archived: bool):
        self.update_student(student_id, {"archived": archived})

    # -- reference data ----------------------------------------------------

    def list_groups(self) -> list:
        return (
            self.client.table("phonics_groups")
            .select("*")
            .order("group_number")
            .execute()
            .data
        )

    def list_sounds(self, group_id: str = None) -> list:
        q = self.client.table("phonics_sounds").select("*").order("order_index")
        if group_id:
            q = q.eq("group_id", group_id)
        return q.execute().data

    # -- phonics tests -----------------------------------------------------

    def save_test_session(self, student_id: str, group_id: str, tested_on: date,
                          results: dict, note: str = None) -> str:
        """One insert for the session, one batched insert for all its results.

        Deliberately not one write per tap: a live test is 6 taps, and 6
        round trips to Supabase in the middle of a lesson is exactly the
        delay this screen exists to avoid.
        """
        session = (
            self.client.table("test_sessions")
            .insert(
                {
                    "student_id": student_id,
                    "group_id": group_id,
                    "tested_on": tested_on.isoformat(),
                    "note": (note or "").strip() or None,
                }
            )
            .execute()
            .data[0]
        )
        rows = [
            {"session_id": session["id"], "sound_id": sid, "status": status}
            for sid, status in results.items()
        ]
        if rows:
            self.client.table("test_results").insert(rows).execute()
        return session["id"]

    def list_test_sessions(self, student_id: str, limit: int = 20) -> list:
        return (
            self.client.table("test_sessions")
            .select("*, phonics_groups(group_number, sounds_preview)")
            .eq("student_id", student_id)
            .order("tested_on", desc=True)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
            .data
        )

    def get_session_results(self, session_id: str) -> list:
        return (
            self.client.table("test_results")
            .select("*, phonics_sounds(code, grapheme, label, order_index)")
            .eq("session_id", session_id)
            .execute()
            .data
        )

    def delete_test_session(self, session_id: str):
        # test_results cascades on the foreign key.
        self.client.table("test_sessions").delete().eq("id", session_id).execute()

    def latest_results_for_group(self, student_id: str, group_id: str) -> dict:
        """{sound_id: status} from this student's most recent test of this group."""
        sessions = (
            self.client.table("test_sessions")
            .select("id")
            .eq("student_id", student_id)
            .eq("group_id", group_id)
            .order("tested_on", desc=True)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        if not sessions:
            return {}
        rows = (
            self.client.table("test_results")
            .select("sound_id, status")
            .eq("session_id", sessions[0]["id"])
            .execute()
            .data
        )
        return {r["sound_id"]: r["status"] for r in rows}

    def group_progress(self, student_ids: list) -> list:
        if not student_ids:
            return []
        return (
            self.client.table("student_group_progress")
            .select("*")
            .in_("student_id", student_ids)
            .execute()
            .data
        )

    # -- class check-ins ---------------------------------------------------

    def latest_checkins(self, student_ids: list) -> dict:
        if not student_ids:
            return {}
        rows = (
            self.client.table("skill_checkins")
            .select("*")
            .in_("student_id", student_ids)
            .order("checkin_date", desc=True)
            .order("created_at", desc=True)
            .execute()
            .data
        )
        latest = {}
        for r in rows:
            latest.setdefault(r["student_id"], r)
        return latest

    def insert_checkins(self, rows: list):
        if rows:
            self.client.table("skill_checkins").insert(rows).execute()

    def list_checkins(self, student_id: str, limit: int = 20) -> list:
        return (
            self.client.table("skill_checkins")
            .select("*")
            .eq("student_id", student_id)
            .order("checkin_date", desc=True)
            .limit(limit)
            .execute()
            .data
        )

    def update_checkin(self, checkin_id: str, fields: dict):
        self.client.table("skill_checkins").update(fields).eq("id", checkin_id).execute()

    def delete_checkin(self, checkin_id: str):
        self.client.table("skill_checkins").delete().eq("id", checkin_id).execute()

    # -- auth --------------------------------------------------------------

    def is_admin(self) -> bool:
        try:
            return bool(self.client.rpc("is_admin").execute().data)
        except Exception:
            return False

    def current_email(self):
        return self.client.auth.get_user().user.email

    def sign_out(self):
        try:
            self.client.auth.sign_out()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Backend selection / auth entry points
# ---------------------------------------------------------------------------

def _supabase_client():
    from supabase import create_client

    return create_client(SUPABASE_URL, SUPABASE_KEY)


def sign_in(email: str, password: str):
    """Returns (backend, refresh_token). Raises on bad credentials."""
    if not USE_SUPABASE:
        from local_backend import SqliteBackend

        return SqliteBackend(), None
    client = _supabase_client()
    res = client.auth.sign_in_with_password({"email": email, "password": password})
    token = res.session.refresh_token if res.session else None
    return SupabaseBackend(client), token


def resume(refresh_token: str):
    """Returns (backend, new_refresh_token) or (None, None)."""
    if not USE_SUPABASE:
        return None, None
    client = _supabase_client()
    res = client.auth.refresh_session(refresh_token)
    if not (res.session and res.session.refresh_token):
        return None, None
    # Supabase rotates refresh tokens: the caller must store the new one.
    return SupabaseBackend(client), res.session.refresh_token


def get_student_sheet(token: str):
    """Anon-key read of the token-gated parent sheet."""
    if not USE_SUPABASE:
        from local_backend import SqliteBackend

        return SqliteBackend().get_student_sheet(token)
    client = _supabase_client()
    return client.rpc("get_student_sheet", {"p_access_token": token}).execute().data
