"""UserRepository tests.

Focus on user_code generation: basic, collisions (6th, 5th, 4th), exhaustion,
insufficient letters, get_or_create existing and new user.

MANDATE: Uses AWS Secrets Manager for DB login via conftest.py fixtures.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from pulldb.infra.mysql import UserRepository


USER_CODE_LEN = 6


class TestUserRepository:
    def _cleanup(self, pool: Any, where: str, params: tuple[Any, ...]) -> None:
        with pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(where, params)
            conn.commit()
            cursor.close()

    def test_generate_user_code_basic(self, mysql_pool: Any) -> None:
        repo = UserRepository(mysql_pool)
        assert repo.generate_user_code("johndoe") == "johndo"
        assert repo.generate_user_code("AliceWonderland") == "alicew"

    def test_generate_user_code_collision_6th_char(self, mysql_pool: Any) -> None:
        repo = UserRepository(mysql_pool)
        user_id = str(uuid.uuid4())
        with mysql_pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM auth_users WHERE user_code IN ('johndo','johnda')"
            )
            cursor.execute(
                (
                    "INSERT INTO auth_users (user_id, username, user_code, "
                    "is_admin, created_at) VALUES "
                    "(%s,'john_existing','johndo',0,UTC_TIMESTAMP(6))"
                ),
                (user_id,),
            )
            conn.commit()
            cursor.close()
        assert repo.generate_user_code("johndavis") == "johnda"
        self._cleanup(
            mysql_pool,
            "DELETE FROM auth_users WHERE user_code IN ('johndo','johnda')",
            (),
        )

    def test_generate_user_code_collision_5th_char(self, mysql_pool: Any) -> None:
        repo = UserRepository(mysql_pool)
        user_id1 = str(uuid.uuid4())
        user_id2 = str(uuid.uuid4())
        with mysql_pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM auth_users WHERE user_code LIKE 'johnd%'")
            cursor.execute(
                (
                    "INSERT INTO auth_users (user_id, username, user_code, "
                    "is_admin, created_at) VALUES "
                    "(%s,'user1','johndo',0,UTC_TIMESTAMP(6))"
                ),
                (user_id1,),
            )
            cursor.execute(
                (
                    "INSERT INTO auth_users (user_id, username, user_code, "
                    "is_admin, created_at) VALUES "
                    "(%s,'user2','johnda',0,UTC_TIMESTAMP(6))"
                ),
                (user_id2,),
            )
            conn.commit()
            cursor.close()
        code = repo.generate_user_code("johndavis")
        assert (
            code.startswith("john")
            and code not in ["johndo", "johnda"]
            and len(code) == USER_CODE_LEN
        )
        self._cleanup(
            mysql_pool, "DELETE FROM auth_users WHERE user_code LIKE 'johnd%'", ()
        )

    def test_generate_user_code_collision_4th_char(self, mysql_pool: Any) -> None:
        repo = UserRepository(mysql_pool)
        ids = [str(uuid.uuid4()) for _ in range(3)]
        with mysql_pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM auth_users WHERE user_code LIKE 'johnd%'")
            for code, uid in zip(["johndo", "johnda", "johndv"], ids, strict=True):
                cursor.execute(
                    (
                        "INSERT INTO auth_users (user_id, username, user_code, "
                        "is_admin, created_at) VALUES "
                        "(%s,%s,%s,0,UTC_TIMESTAMP(6))"
                    ),
                    (uid, f"user_{code}", code),
                )
            conn.commit()
            cursor.close()
        code = repo.generate_user_code("johndavidson")
        assert (
            code.startswith("john")
            and code not in ["johndo", "johnda", "johndv"]
            and len(code) == USER_CODE_LEN
        )
        self._cleanup(
            mysql_pool, "DELETE FROM auth_users WHERE user_code LIKE 'johnd%'", ()
        )

    def test_generate_user_code_exhausted(self, mysql_pool: Any) -> None:
        repo = UserRepository(mysql_pool)
        username = "aaaaaabbbbbaaaaaabbbbba"
        # Use distinct codes with unique usernames; previous failure was due to
        # duplicate username value causing IntegrityError on UNIQUE(username).
        variants = ["aaaaaa", "aaaaab", "aaaaba", "aaabaa"]
        with mysql_pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM auth_users WHERE user_code LIKE 'aaaa%'")
            for v in variants:
                # Skip insert if code already exists
                cursor.execute(
                    "SELECT COUNT(*) FROM auth_users WHERE user_code = %s",
                    (v,),
                )
                if cursor.fetchone()[0] == 0:
                    cursor.execute(
                        (
                            "INSERT INTO auth_users (user_id, username, user_code, "
                            "is_admin, created_at) VALUES "
                            "(%s,%s,%s,0,UTC_TIMESTAMP(6))"
                        ),
                        (str(uuid.uuid4()), f"user_{v}_{uuid.uuid4().hex[:8]}", v),
                    )
            conn.commit()
            cursor.close()
        with pytest.raises(ValueError):
            repo.generate_user_code(username)
        self._cleanup(
            mysql_pool, "DELETE FROM auth_users WHERE user_code LIKE 'aaaa%'", ()
        )

    def test_generate_user_code_insufficient_letters(self, mysql_pool: Any) -> None:
        repo = UserRepository(mysql_pool)
        for bad in ["abc", "a1b2c", "123456", "ab!!cd"]:
            with pytest.raises(ValueError):
                repo.generate_user_code(bad)

    def test_get_or_create_user_existing(self, mysql_pool: Any) -> None:
        repo = UserRepository(mysql_pool)
        username = "existinguserexample"
        code = repo.generate_user_code(username)
        user_id = str(uuid.uuid4())
        with mysql_pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                (
                    "INSERT INTO auth_users (user_id, username, user_code, "
                    "is_admin, created_at) VALUES "
                    "(%s,%s,%s,0,UTC_TIMESTAMP(6))"
                ),
                (user_id, username, code),
            )
            conn.commit()
            cursor.close()
        user = repo.get_or_create_user(username)
        assert (
            user.user_id == user_id
            and user.user_code == code
            and user.username == username
        )
        self._cleanup(
            mysql_pool, "DELETE FROM auth_users WHERE user_id = %s", (user_id,)
        )

    def test_get_or_create_user_new(self, mysql_pool: Any) -> None:
        repo = UserRepository(mysql_pool)
        username = "brandnewuniqueuser"
        with mysql_pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM auth_users WHERE username = %s", (username,))
            conn.commit()
            cursor.close()
        user = repo.get_or_create_user(username)
        assert user.username == username and len(user.user_code) == USER_CODE_LEN
        self._cleanup(
            mysql_pool, "DELETE FROM auth_users WHERE user_id = %s", (user.user_id,)
        )
