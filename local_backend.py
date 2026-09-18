"""Offline SQLite backend -- development and review only.

This exists so the whole app can be clicked through before the teacher has
a Supabase account. It implements the same method contract as
db.SupabaseBackend against a local `demo.db`, and is selected only when
SUPABASE_URL / SUPABASE_KEY are absent (or PHONICS_DEMO=1 is set).

It is NOT a security boundary: there is no login and no RLS. Nothing here
runs once real credentials are configured -- see db.USE_SUPABASE.

The 42 letter sounds are parsed out of seed_phonics.sql rather than
duplicated here, so the demo can never drift from what Supabase is seeded
with.
"""

from __future__ import annotations

import os
import re
import sqlite3
import uuid
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "demo.db")
SEED_SQL = os.path.join(HERE, "seed_phonics.sql")

SCHEMA = """
create table if not exists classes (
  id text primary key, name text not null, level text,
  archived int not null default 0, created_at text default (datetime('now')));
create table if not exists students (
  id text primary key, class_id text, name text not null, parent_contact text,
  photo_b64 text, access_token text unique not null,
  archived int not null default 0, created_at text default (datetime('now')));
create table if not exists phonics_groups (
  id text primary key, group_number int not null unique, sounds_preview text not null);
create table if not exists phonics_sounds (
  id text primary key, group_id text not null, code text not null unique,
  grapheme text not null, label text not null, example_word text,
  action_hint text, order_index int not null);
create table if not exists test_sessions (
  id text primary key, student_id text not null, group_id text not null,
  tested_on text not null, note text, created_at text default (datetime('now')));
create table if not exists test_results (
  id text primary key, session_id text not null, sound_id text not null,
  status text not null, unique (session_id, sound_id));
create table if not exists skill_checkins (
  id text primary key, student_id text not null, checkin_date text not null,
  blending_rating int, segmenting_rating int, letter_formation_rating int,
  pencil_grip_rating int, tricky_words_rating int, participation_rating int,
  notes text, created_at text default (datetime('now')));
"""


def _uid() -> str:
    return str(uuid.uuid4())


def _parse_seed():
    """Pull the groups and the 42 sounds straight out of seed_phonics.sql."""
    sql = open(SEED_SQL).read()
    gblock = sql.split("insert into phonics_groups", 1)[1].split("on conflict", 1)[0]
    groups = [(int(n), p) for n, p in re.findall(r"\((\d),\s*'([^']*)'\)", gblock)]

    sblock = sql.split("from (values", 1)[1].split(") as v(", 1)[0]
    sounds = []
    for gnum, mid, order in re.findall(
        r"\(\s*(\d)\s*,\s*((?:'(?:[^']|'')*'\s*,\s*){5})(\d+)\s*\)", sblock
    ):
        parts = [p.replace("''", "'") for p in re.findall(r"'((?:[^']|'')*)'", mid)]
        code, grapheme, label, example, action = parts
        sounds.append((int(gnum), code, grapheme, label, example, action, int(order)))
    return groups, sounds


class SqliteBackend:
    """Same contract as db.SupabaseBackend, backed by a local file."""

    is_demo = True

    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._seed_reference()
        self._seed_demo_roster()
        self.conn.commit()

    # -- seeding -----------------------------------------------------------

    def _seed_reference(self):
        groups, sounds = _parse_seed()
        gid_by_num = {}
        for num, preview in groups:
            row = self.conn.execute(
                "select id from phonics_groups where group_number=?", (num,)
            ).fetchone()
            if row:
                gid_by_num[num] = row["id"]
                self.conn.execute(
                    "update phonics_groups set sounds_preview=? where id=?",
                    (preview, row["id"]),
                )
            else:
                gid = _uid()
                gid_by_num[num] = gid
                self.conn.execute(
                    "insert into phonics_groups (id, group_number, sounds_preview)"
                    " values (?,?,?)",
                    (gid, num, preview),
                )
        for gnum, code, grapheme, label, example, action, order in sounds:
            self.conn.execute(
                "insert into phonics_sounds"
                " (id, group_id, code, grapheme, label, example_word, action_hint, order_index)"
                " values (?,?,?,?,?,?,?,?)"
                " on conflict(code) do update set grapheme=excluded.grapheme,"
                " label=excluded.label, example_word=excluded.example_word,"
                " action_hint=excluded.action_hint, order_index=excluded.order_index",
                (_uid(), gid_by_num[gnum], code, grapheme, label, example, action, order),
            )

    def _seed_demo_roster(self):
        """A small fake class, so the screens have something to show."""
        if self.conn.execute("select count(*) c from classes").fetchone()["c"]:
            return
        cid = _uid()
        self.conn.execute(
            "insert into classes (id, name, level) values (?,?,?)",
            (cid, "Phonics Beginners (demo)", "Jolly Phonics 1"),
        )
        groups = {
            r["group_number"]: r["id"]
            for r in self.conn.execute("select * from phonics_groups")
        }
        # Three children at deliberately different stages, so the roll-up
        # ("mastered 1-2, working on 3") is visible straight away.
        plan = [
            ("An (demo)", 3, 4),      # groups 1-3 done, group 4 part-way
            ("Binh (demo)", 1, 2),
            ("Chi (demo)", 0, 1),
        ]
        for name, done_through, working_on in plan:
            sid = _uid()
            self.conn.execute(
                "insert into students (id, class_id, name, access_token) values (?,?,?,?)",
                (sid, cid, name, uuid.uuid4().hex),
            )
            for gnum in range(1, working_on + 1):
                sounds = self.conn.execute(
                    "select id from phonics_sounds where group_id=? order by order_index",
                    (groups[gnum],),
                ).fetchall()
                sess = _uid()
                self.conn.execute(
                    "insert into test_sessions (id, student_id, group_id, tested_on)"
                    " values (?,?,?,?)",
                    (sess, sid, groups[gnum],
                     (date.today() - timedelta(days=7 * (working_on - gnum + 1))).isoformat()),
                )
                for i, snd in enumerate(sounds):
                    if gnum <= done_through:
                        status = "acquired"
                    else:
                        status = ["acquired", "acquired", "practising",
                                  "practising", "not_yet", "not_yet"][i % 6]
                    self.conn.execute(
                        "insert into test_results (id, session_id, sound_id, status)"
                        " values (?,?,?,?)",
                        (_uid(), sess, snd["id"], status),
                    )
            self.conn.execute(
                "insert into skill_checkins (id, student_id, checkin_date,"
                " blending_rating, segmenting_rating, letter_formation_rating,"
                " pencil_grip_rating, tricky_words_rating, participation_rating)"
                " values (?,?,?,?,?,?,?,?,?)",
                (_uid(), sid, (date.today() - timedelta(days=7)).isoformat(),
                 min(4, working_on + 1), working_on, min(4, working_on + 1),
                 3, working_on, 4),
            )

    # -- helpers -----------------------------------------------------------

    def _rows(self, sql, args=()) -> list:
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    # -- roster ------------------------------------------------------------

    def list_classes(self, include_archived: bool = False) -> list:
        sql = "select * from classes"
        if not include_archived:
            sql += " where archived=0"
        rows = self._rows(sql + " order by created_at")
        for r in rows:
            r["archived"] = bool(r["archived"])
        return rows

    def add_class(self, name, level=None):
        self.conn.execute(
            "insert into classes (id, name, level) values (?,?,?)",
            (_uid(), name, level or None),
        )
        self.conn.commit()

    def set_class_archived(self, class_id, archived):
        self.conn.execute(
            "update classes set archived=? where id=?", (int(archived), class_id)
        )
        self.conn.commit()

    def list_students(self, class_id=None, include_archived=False) -> list:
        sql = ("select s.*, c.name as _class_name, c.id as _class_id"
               " from students s left join classes c on c.id = s.class_id where 1=1")
        args = []
        if class_id:
            sql += " and s.class_id=?"
            args.append(class_id)
        if not include_archived:
            sql += " and s.archived=0"
        rows = self._rows(sql + " order by s.name", args)
        for r in rows:
            r["archived"] = bool(r["archived"])
            cid, cname = r.pop("_class_id"), r.pop("_class_name")
            # Mirrors supabase-py's embedded-resource shape: None when unassigned.
            r["classes"] = {"id": cid, "name": cname} if cid else None
        return rows

    def add_student(self, class_id, name, parent_contact=None, photo_b64=None):
        self.conn.execute(
            "insert into students (id, class_id, name, parent_contact, photo_b64,"
            " access_token) values (?,?,?,?,?,?)",
            (_uid(), class_id, name, parent_contact or None, photo_b64, uuid.uuid4().hex),
        )
        self.conn.commit()

    def update_student(self, student_id, fields: dict):
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(
            f"update students set {sets} where id=?", (*fields.values(), student_id)
        )
        self.conn.commit()

    def set_student_archived(self, student_id, archived):
        self.update_student(student_id, {"archived": int(archived)})

    # -- reference data ----------------------------------------------------

    def list_groups(self) -> list:
        return self._rows("select * from phonics_groups order by group_number")

    def list_sounds(self, group_id=None) -> list:
        if group_id:
            return self._rows(
                "select * from phonics_sounds where group_id=? order by order_index",
                (group_id,),
            )
        return self._rows("select * from phonics_sounds order by order_index")

    # -- phonics tests -----------------------------------------------------

    def save_test_session(self, student_id, group_id, tested_on, results, note=None) -> str:
        sess = _uid()
        self.conn.execute(
            "insert into test_sessions (id, student_id, group_id, tested_on, note)"
            " values (?,?,?,?,?)",
            (sess, student_id, group_id, tested_on.isoformat(),
             (note or "").strip() or None),
        )
        for sid, status in results.items():
            self.conn.execute(
                "insert into test_results (id, session_id, sound_id, status) values (?,?,?,?)",
                (_uid(), sess, sid, status),
            )
        self.conn.commit()
        return sess

    def list_test_sessions(self, student_id, limit=20) -> list:
        rows = self._rows(
            "select t.*, g.group_number as _gnum, g.sounds_preview as _preview"
            " from test_sessions t join phonics_groups g on g.id = t.group_id"
            " where t.student_id=? order by t.tested_on desc, t.created_at desc limit ?",
            (student_id, limit),
        )
        for r in rows:
            r["phonics_groups"] = {
                "group_number": r.pop("_gnum"),
                "sounds_preview": r.pop("_preview"),
            }
        return rows

    def get_session_results(self, session_id) -> list:
        rows = self._rows(
            "select r.*, p.code as _code, p.grapheme as _g, p.label as _l,"
            " p.order_index as _o from test_results r"
            " join phonics_sounds p on p.id = r.sound_id where r.session_id=?"
            " order by p.order_index",
            (session_id,),
        )
        for r in rows:
            r["phonics_sounds"] = {
                "code": r.pop("_code"), "grapheme": r.pop("_g"),
                "label": r.pop("_l"), "order_index": r.pop("_o"),
            }
        return rows

    def delete_test_session(self, session_id):
        self.conn.execute("delete from test_results where session_id=?", (session_id,))
        self.conn.execute("delete from test_sessions where id=?", (session_id,))
        self.conn.commit()

    def latest_results_for_group(self, student_id, group_id) -> dict:
        row = self.conn.execute(
            "select id from test_sessions where student_id=? and group_id=?"
            " order by tested_on desc, created_at desc limit 1",
            (student_id, group_id),
        ).fetchone()
        if not row:
            return {}
        return {
            r["sound_id"]: r["status"]
            for r in self.conn.execute(
                "select sound_id, status from test_results where session_id=?", (row["id"],)
            )
        }

    def group_progress(self, student_ids: list) -> list:
        """Python equivalent of the student_group_progress view."""
        if not student_ids:
            return []
        current = {}  # (student, sound) -> (status, tested_on)
        marks = ",".join("?" * len(student_ids))
        for r in self.conn.execute(
            "select t.student_id, r.sound_id, r.status, t.tested_on, t.created_at"
            f" from test_sessions t join test_results r on r.session_id = t.id"
            f" where t.student_id in ({marks})"
            " order by t.tested_on asc, t.created_at asc",
            student_ids,
        ):
            # Ascending order means the last write per key wins = the latest test.
            current[(r["student_id"], r["sound_id"])] = (r["status"], r["tested_on"])

        groups = self._rows("select * from phonics_groups order by group_number")
        sounds_by_group = {}
        for s in self._rows("select * from phonics_sounds"):
            sounds_by_group.setdefault(s["group_id"], []).append(s)

        out = []
        for sid in student_ids:
            for g in groups:
                sounds = sounds_by_group.get(g["id"], [])
                seen = [current.get((sid, s["id"])) for s in sounds]
                seen = [x for x in seen if x]
                out.append({
                    "student_id": sid,
                    "group_id": g["id"],
                    "group_number": g["group_number"],
                    "total_sounds": len(sounds),
                    "acquired": sum(1 for st, _ in seen if st == "acquired"),
                    "practising": sum(1 for st, _ in seen if st == "practising"),
                    "not_yet": sum(1 for st, _ in seen if st == "not_yet"),
                    "last_tested_on": max((d for _, d in seen), default=None),
                })
        return out

    # -- class check-ins ---------------------------------------------------

    def latest_checkins(self, student_ids: list) -> dict:
        if not student_ids:
            return {}
        marks = ",".join("?" * len(student_ids))
        rows = self._rows(
            f"select * from skill_checkins where student_id in ({marks})"
            " order by checkin_date desc, created_at desc",
            student_ids,
        )
        latest = {}
        for r in rows:
            latest.setdefault(r["student_id"], r)
        return latest

    def insert_checkins(self, rows: list):
        for r in rows:
            cols = ["student_id", "checkin_date", "notes"] + [
                k for k in r if k.endswith("_rating")
            ]
            vals = [r.get(c) for c in cols]
            self.conn.execute(
                f"insert into skill_checkins (id, {', '.join(cols)})"
                f" values (?{', ?' * len(cols)})",
                (_uid(), *vals),
            )
        self.conn.commit()

    def list_checkins(self, student_id, limit=20) -> list:
        return self._rows(
            "select * from skill_checkins where student_id=?"
            " order by checkin_date desc, created_at desc limit ?",
            (student_id, limit),
        )

    def update_checkin(self, checkin_id, fields: dict):
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(
            f"update skill_checkins set {sets} where id=?", (*fields.values(), checkin_id)
        )
        self.conn.commit()

    def delete_checkin(self, checkin_id):
        self.conn.execute("delete from skill_checkins where id=?", (checkin_id,))
        self.conn.commit()

    # -- auth (no-op: demo mode has no accounts) ---------------------------

    def is_admin(self) -> bool:
        return True

    def current_email(self) -> str:
        return "demo@local"

    def sign_out(self):
        pass

    # -- parent sheet ------------------------------------------------------

    def get_student_sheet(self, token: str):
        row = self.conn.execute(
            "select s.*, c.name as class_name from students s"
            " left join classes c on c.id = s.class_id"
            " where s.access_token=? and s.archived=0",
            (token,),
        ).fetchone()
        if not row:
            return None
        sid = row["id"]
        progress = self.group_progress([sid])
        previews = {
            g["group_number"]: g["sounds_preview"] for g in self.list_groups()
        }
        sounds = {s["id"]: s for s in self.list_sounds()}
        gnum_by_id = {g["id"]: g["group_number"] for g in self.list_groups()}
        practise = []
        for (_sid, sound_id), (status, _d) in self._current_map([sid]).items():
            if status == "acquired":
                continue
            s = sounds[sound_id]
            practise.append({
                "code": s["code"],
                "grapheme": s["grapheme"], "label": s["label"],
                "example_word": s["example_word"], "status": status,
                "group_number": gnum_by_id[s["group_id"]],
                "_order": (gnum_by_id[s["group_id"]], s["order_index"]),
            })
        practise.sort(key=lambda p: p.pop("_order"))
        timeline = self._rows(
            "select t.tested_on, g.group_number,"
            " (select count(*) from test_results r where r.session_id=t.id"
            "   and r.status='acquired') as secure,"
            " (select count(*) from test_results r where r.session_id=t.id) as total"
            " from test_sessions t join phonics_groups g on g.id=t.group_id"
            " where t.student_id=? order by t.tested_on desc, t.created_at desc limit 10",
            (sid,),
        )
        checkins = self.list_checkins(sid, limit=1)
        return {
            "timeline": timeline,
            "student": {
                "name": row["name"], "photo_b64": row["photo_b64"],
                "class_name": row["class_name"],
            },
            "groups": [
                {**p, "sounds_preview": previews[p["group_number"]]}
                for p in sorted(progress, key=lambda p: p["group_number"])
            ],
            "practise": practise,
            "last_checkin": checkins[0] if checkins else None,
        }

    def _current_map(self, student_ids):
        marks = ",".join("?" * len(student_ids))
        current = {}
        for r in self.conn.execute(
            "select t.student_id, r.sound_id, r.status, t.tested_on"
            " from test_sessions t join test_results r on r.session_id = t.id"
            f" where t.student_id in ({marks})"
            " order by t.tested_on asc, t.created_at asc",
            student_ids,
        ):
            current[(r["student_id"], r["sound_id"])] = (r["status"], r["tested_on"])
        return current
