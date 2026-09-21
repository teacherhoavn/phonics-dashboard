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
  id text primary key, class_id text, name text not null,
  parent_name text, parent_contact text, order_index int,
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
create table if not exists checkin_criteria (
  id text primary key, code text not null unique, name_en text not null,
  name_vi text not null, short_label text not null, description_en text,
  order_index int not null, active int not null default 1,
  parent_visible int not null default 1);
create table if not exists checkins (
  id text primary key, student_id text not null, checkin_date text not null,
  absent int not null default 0, notes text,
  created_at text default (datetime('now')), unique (student_id, checkin_date));
create table if not exists checkin_scores (
  checkin_id text not null, criterion_id text not null, score int not null,
  primary key (checkin_id, criterion_id));
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
        self._add_missing_columns()
        self._seed_reference()
        self._seed_criteria()
        self._seed_demo_roster()
        self.conn.commit()

    def _add_missing_columns(self):
        """"create table if not exists" never adds a column to a file that
        already exists, so a demo.db made before a schema change would crash
        on the new fields. Add anything missing instead of asking whoever is
        developing to delete their demo data."""
        added = {
            "students": {"parent_name": "text", "order_index": "int"},
        }
        for table, columns in added.items():
            have = {r["name"] for r in self.conn.execute(f"pragma table_info({table})")}
            for column, coltype in columns.items():
                if column not in have:
                    self.conn.execute(f"alter table {table} add column {column} {coltype}")
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

    DEFAULT_CRITERIA = [
        ("participation", "Participation", "Tham gia", "Part.",
         "Joins in, answers, tries without being asked"),
        ("behaviour", "Behaviour", "Ý thức trong lớp", "Behav.",
         "Listens, follows instructions, works well with others"),
        ("homework", "Homework", "Bài tập về nhà", "H/W",
         "Homework done, and done with care"),
        ("pronunciation", "Pronunciation", "Phát âm", "Pron.",
         "Says the sounds clearly and accurately"),
        ("correct_use", "Correct use", "Dùng đúng", "Use",
         "Uses the right English in the right situation"),
        ("vocabulary", "Vocabulary", "Từ vựng", "Vocab",
         "Knows and uses the words taught"),
    ]

    def _seed_criteria(self):
        for i, (code, en, vi, short, desc) in enumerate(self.DEFAULT_CRITERIA, 1):
            self.conn.execute(
                "insert into checkin_criteria (id, code, name_en, name_vi,"
                " short_label, description_en, order_index) values (?,?,?,?,?,?,?)"
                " on conflict(code) do update set name_en=excluded.name_en,"
                " name_vi=excluded.name_vi, short_label=excluded.short_label",
                (_uid(), code, en, vi, short, desc, i),
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
        for position, (name, done_through, working_on) in enumerate(plan, 1):
            sid = _uid()
            self.conn.execute(
                "insert into students (id, class_id, name, access_token, order_index)"
                " values (?,?,?,?,?)",
                (sid, cid, name, uuid.uuid4().hex, position),
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
            for offset, factor in ((17, 0), (3, 1)):
                cid = _uid()
                self.conn.execute(
                    "insert into checkins (id, student_id, checkin_date) values (?,?,?)",
                    (cid, sid, (date.today() - timedelta(days=offset)).isoformat()))
                for n, row in enumerate(self.conn.execute(
                        "select id from checkin_criteria order by order_index").fetchall()):
                    self.conn.execute(
                        "insert into checkin_scores (checkin_id, criterion_id, score)"
                        " values (?,?,?)",
                        (cid, row["id"], min(10, 4 + working_on + factor + (n % 3))))

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

    def update_class(self, class_id, fields: dict):
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"update classes set {sets} where id=?",
                          (*fields.values(), class_id))
        self.conn.commit()

    def delete_class(self, class_id):
        """Refused while the class still has students -- see SupabaseBackend."""
        if self.list_students(class_id=class_id, include_archived=True):
            raise ValueError("That class still has students.")
        self.conn.execute("delete from classes where id=?", (class_id,))
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
        rows = self._rows(sql, args)
        for r in rows:
            r["archived"] = bool(r["archived"])
            cid, cname = r.pop("_class_id"), r.pop("_class_name")
            # Mirrors supabase-py's embedded-resource shape: None when unassigned.
            r["classes"] = {"id": cid, "name": cname} if cid else None
        from db import roster_order

        return roster_order(rows)

    def add_student(self, class_id, name, parent_contact=None, photo_b64=None,
                    parent_name=None, order_index=None):
        self.conn.execute(
            "insert into students (id, class_id, name, parent_name, parent_contact,"
            " photo_b64, access_token, order_index) values (?,?,?,?,?,?,?,?)",
            (_uid(), class_id, name, parent_name or None, parent_contact or None,
             photo_b64, uuid.uuid4().hex, order_index),
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

    # -- lesson check-ins --------------------------------------------------

    def list_criteria(self, include_inactive: bool = False) -> list:
        sql = "select * from checkin_criteria"
        if not include_inactive:
            sql += " where active=1"
        rows = self._rows(sql + " order by order_index")
        for r in rows:
            r["active"] = bool(r["active"])
            r["parent_visible"] = bool(r["parent_visible"])
        return rows

    def add_criterion(self, fields: dict):
        cols = list(fields)
        self.conn.execute(
            f"insert into checkin_criteria (id, {', '.join(cols)})"
            f" values (?{', ?' * len(cols)})",
            (_uid(), *[fields[c] for c in cols]))
        self.conn.commit()

    def update_criterion(self, criterion_id, fields: dict):
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"update checkin_criteria set {sets} where id=?",
                          (*fields.values(), criterion_id))
        self.conn.commit()

    def save_checkin(self, student_id, on_date, scores: dict,
                     absent: bool = False, notes: str = None):
        row = self.conn.execute(
            "select id from checkins where student_id=? and checkin_date=?",
            (student_id, on_date.isoformat())).fetchone()
        cid = row["id"] if row else _uid()
        if row:
            self.conn.execute(
                "update checkins set absent=?, notes=? where id=?",
                (int(absent), (notes or "").strip() or None, cid))
        else:
            self.conn.execute(
                "insert into checkins (id, student_id, checkin_date, absent, notes)"
                " values (?,?,?,?,?)",
                (cid, student_id, on_date.isoformat(), int(absent),
                 (notes or "").strip() or None))
        self.conn.execute("delete from checkin_scores where checkin_id=?", (cid,))
        if not absent:
            for crit, value in (scores or {}).items():
                if value:
                    self.conn.execute(
                        "insert into checkin_scores (checkin_id, criterion_id, score)"
                        " values (?,?,?)", (cid, crit, int(value)))
        self.conn.commit()
        return cid

    def _scores_for(self, checkin_id) -> dict:
        return {r["criterion_id"]: r["score"] for r in self.conn.execute(
            "select criterion_id, score from checkin_scores where checkin_id=?",
            (checkin_id,))}

    def checkins_on(self, student_ids: list, on_date) -> dict:
        if not student_ids:
            return {}
        marks = ",".join("?" * len(student_ids))
        out = {}
        for r in self._rows(
                f"select * from checkins where student_id in ({marks})"
                " and checkin_date=?", (*student_ids, on_date.isoformat())):
            out[r["student_id"]] = {"absent": bool(r["absent"]), "notes": r["notes"],
                                    "scores": self._scores_for(r["id"])}
        return out

    def latest_checkins(self, student_ids: list) -> dict:
        if not student_ids:
            return {}
        marks = ",".join("?" * len(student_ids))
        latest = {}
        for r in self._rows(
                f"select * from checkins where student_id in ({marks})"
                " order by checkin_date desc", student_ids):
            latest.setdefault(r["student_id"], {
                "checkin_date": r["checkin_date"], "absent": bool(r["absent"]),
                "scores": self._scores_for(r["id"])})
        return latest

    def list_student_checkins(self, student_id, limit: int = 20) -> list:
        rows = self._rows(
            "select * from checkins where student_id=?"
            " order by checkin_date desc limit ?", (student_id, limit))
        for r in rows:
            r["absent"] = bool(r["absent"])
            r["scores"] = self._scores_for(r["id"])
        return rows

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
        criteria = [c for c in self.list_criteria() if c["parent_visible"]]
        recent = self.list_student_checkins(sid, limit=12)
        attended = [c for c in recent if not c["absent"] and c["scores"]]

        # Radar: each criterion averaged over the last four attended lessons.
        last_four = attended[:4]
        radar = {}
        for c in criteria:
            vals = [x["scores"][c["id"]] for x in last_four if c["id"] in x["scores"]]
            if vals:
                radar[c["code"]] = round(sum(vals) / len(vals), 2)

        # Trend: one point per attended lesson, oldest first. Absences are
        # simply absent, so the line gaps rather than dropping to zero.
        trend = [
            {"date": x["checkin_date"],
             "average": round(sum(x["scores"].values()) / len(x["scores"]), 2)}
            for x in reversed(attended)
        ]

        last = recent[0] if recent else None
        last_checkin = None
        if last:
            by_id = {c["id"]: c["code"] for c in criteria}
            last_checkin = {
                "checkin_date": last["checkin_date"],
                "absent": last["absent"],
                "notes": last["notes"],
                "scores": {by_id[k]: v for k, v in last["scores"].items()
                           if k in by_id},
            }

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
            "criteria": [{"code": c["code"], "name_vi": c["name_vi"]} for c in criteria],
            "radar": radar,
            "trend": trend,
            "last_checkin": last_checkin,
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
