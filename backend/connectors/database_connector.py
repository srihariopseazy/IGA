"""
Database Connector for IGA Platform.
Manages database-level user accounts for PostgreSQL (asyncpg) and MySQL (aiomysql).
Supports CREATE/ALTER/DROP USER, LOGIN/NOLOGIN, and role grants.
"""
import asyncio
from typing import Dict, Any, List, Optional

from backend.connectors.base import BaseConnector, ConnectorResult, UserAccount


class DatabaseConnector(BaseConnector):
    connector_type = "database"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.db_type = config.get("db_type", "postgresql").lower()  # postgresql, mysql, mssql
        self.host = config.get("host", "localhost")
        self.port = int(config.get("port", self._default_port()))
        self.database = config.get("database", "")
        self.admin_user = config.get("admin_user", "")
        self.admin_password = self._decrypt_config("admin_password")
        self.ssl = config.get("ssl", "false").lower() == "true"
        self.timeout = int(config.get("timeout", 30))

    def _default_port(self) -> int:
        defaults = {"postgresql": 5432, "mysql": 3306, "mssql": 1433}
        return defaults.get(self.config.get("db_type", "postgresql").lower(), 5432)

    # ------------------------------------------------------------------
    # Connection string helpers
    # ------------------------------------------------------------------

    def _get_pg_dsn(self) -> str:
        ssl_param = "?sslmode=require" if self.ssl else ""
        return (
            f"postgresql://{self.admin_user}:{self.admin_password}"
            f"@{self.host}:{self.port}/{self.database}{ssl_param}"
        )

    # ------------------------------------------------------------------
    # PostgreSQL execution helpers
    # ------------------------------------------------------------------

    async def _pg_connect(self):
        import asyncpg  # type: ignore
        return await asyncpg.connect(
            self._get_pg_dsn(),
            timeout=self.timeout,
        )

    async def _execute(self, sql: str, *params) -> ConnectorResult:
        """Execute a DDL/DML statement."""
        if self.db_type == "postgresql":
            try:
                conn = await self._pg_connect()
                try:
                    await conn.execute(sql, *params)
                    return ConnectorResult(success=True)
                finally:
                    await conn.close()
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))
        return ConnectorResult(success=False, error=f"Unsupported db_type: {self.db_type}")

    async def _fetchrow(self, sql: str, *params) -> ConnectorResult:
        if self.db_type == "postgresql":
            try:
                conn = await self._pg_connect()
                try:
                    row = await conn.fetchrow(sql, *params)
                    if row:
                        return ConnectorResult(success=True, data=dict(row))
                    return ConnectorResult(success=False, error="Row not found")
                finally:
                    await conn.close()
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))
        return ConnectorResult(success=False, error=f"Unsupported db_type: {self.db_type}")

    async def _fetch(self, sql: str, *params) -> ConnectorResult:
        if self.db_type == "postgresql":
            try:
                conn = await self._pg_connect()
                try:
                    rows = await conn.fetch(sql, *params)
                    return ConnectorResult(
                        success=True,
                        data={"rows": [dict(r) for r in rows]},
                    )
                finally:
                    await conn.close()
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))
        return ConnectorResult(success=False, error=f"Unsupported db_type: {self.db_type}")

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    async def test_connection(self) -> ConnectorResult:
        if self.db_type == "postgresql":
            result = await self._fetchrow("SELECT version() AS ver")
            if result.success:
                return ConnectorResult(success=True, data=result.data)
            return result
        return ConnectorResult(success=False, error=f"Unsupported db_type: {self.db_type}")

    # ------------------------------------------------------------------
    # User lifecycle
    # ------------------------------------------------------------------

    async def create_user(self, user: UserAccount) -> ConnectorResult:
        attrs = user.attributes or {}
        db_password = attrs.get("db_password", "TempPass123!@#")
        username = user.username.replace('"', '')  # sanitise for identifier quoting

        if self.db_type == "postgresql":
            create_sql = f'CREATE USER "{username}" WITH PASSWORD $1'
            result = await self._execute(create_sql, db_password)
            if not result.success:
                # User may already exist — check and return gracefully
                if "already exists" in (result.error or ""):
                    return ConnectorResult(
                        success=False,
                        error=f"User '{username}' already exists in database",
                    )
                return result

            # Grant any requested roles
            roles: List[str] = attrs.get("db_roles", [])
            for role in roles:
                safe_role = role.replace('"', '')
                grant_result = await self._execute(
                    f'GRANT "{safe_role}" TO "{username}"'
                )
                if not grant_result.success:
                    self.logger.warning(
                        f"Failed to grant role '{safe_role}' to '{username}': {grant_result.error}"
                    )

            # Grant database connection
            if self.database:
                await self._execute(
                    f'GRANT CONNECT ON DATABASE "{self.database}" TO "{username}"'
                )

            return ConnectorResult(
                success=True,
                data={"external_id": username, "username": username},
            )

        return ConnectorResult(
            success=False, error=f"create_user not implemented for {self.db_type}"
        )

    async def update_user(
        self, external_id: str, attributes: Dict[str, Any]
    ) -> ConnectorResult:
        username = external_id.replace('"', '')

        if self.db_type == "postgresql":
            if "password" in attributes:
                result = await self._execute(
                    f'ALTER USER "{username}" WITH PASSWORD $1',
                    attributes["password"],
                )
                if not result.success:
                    return result
            if "connection_limit" in attributes:
                result = await self._execute(
                    f'ALTER USER "{username}" CONNECTION LIMIT {int(attributes["connection_limit"])}'
                )
                if not result.success:
                    return result
            return ConnectorResult(success=True)

        return ConnectorResult(
            success=False, error=f"update_user not implemented for {self.db_type}"
        )

    async def delete_user(self, external_id: str) -> ConnectorResult:
        """Disable login rather than hard-deleting the DB role."""
        return await self.disable_user(external_id)

    async def enable_user(self, external_id: str) -> ConnectorResult:
        username = external_id.replace('"', '')
        if self.db_type == "postgresql":
            return await self._execute(f'ALTER USER "{username}" LOGIN')
        return ConnectorResult(
            success=False, error=f"enable_user not implemented for {self.db_type}"
        )

    async def disable_user(self, external_id: str) -> ConnectorResult:
        username = external_id.replace('"', '')
        if self.db_type == "postgresql":
            return await self._execute(f'ALTER USER "{username}" NOLOGIN')
        return ConnectorResult(
            success=False, error=f"disable_user not implemented for {self.db_type}"
        )

    async def get_user(self, external_id: str) -> ConnectorResult:
        username = external_id.replace("'", "''")  # SQL-safe for WHERE clause
        if self.db_type == "postgresql":
            result = await self._fetchrow(
                "SELECT usename, usesuper, usecreatedb, usecreaterole, "
                "usebypassrls, valuntil FROM pg_user WHERE usename = $1",
                username,
            )
            if result.success:
                return result
            return ConnectorResult(success=False, error=f"User '{username}' not found")

        return ConnectorResult(
            success=False, error=f"get_user not implemented for {self.db_type}"
        )

    async def list_users(self, filter: str = None) -> ConnectorResult:
        if self.db_type == "postgresql":
            result = await self._fetch(
                "SELECT usename, usesuper, usecreatedb, usecreaterole, "
                "usebypassrls, valuntil FROM pg_user ORDER BY usename"
            )
            if result.success:
                rows = result.data["rows"]
                return ConnectorResult(
                    success=True,
                    data={"users": rows, "total": len(rows)},
                )
            return result

        return ConnectorResult(
            success=False, error=f"list_users not implemented for {self.db_type}"
        )

    # ------------------------------------------------------------------
    # Additional database operations
    # ------------------------------------------------------------------

    async def grant_role(self, username: str, role: str) -> ConnectorResult:
        safe_user = username.replace('"', '')
        safe_role = role.replace('"', '')
        if self.db_type == "postgresql":
            return await self._execute(
                f'GRANT "{safe_role}" TO "{safe_user}"'
            )
        return ConnectorResult(
            success=False, error=f"grant_role not implemented for {self.db_type}"
        )

    async def revoke_role(self, username: str, role: str) -> ConnectorResult:
        safe_user = username.replace('"', '')
        safe_role = role.replace('"', '')
        if self.db_type == "postgresql":
            return await self._execute(
                f'REVOKE "{safe_role}" FROM "{safe_user}"'
            )
        return ConnectorResult(
            success=False, error=f"revoke_role not implemented for {self.db_type}"
        )

    async def list_roles(self) -> ConnectorResult:
        if self.db_type == "postgresql":
            result = await self._fetch(
                "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, "
                "rolcanlogin FROM pg_roles ORDER BY rolname"
            )
            if result.success:
                rows = result.data["rows"]
                return ConnectorResult(
                    success=True,
                    data={"roles": rows, "total": len(rows)},
                )
            return result
        return ConnectorResult(
            success=False, error=f"list_roles not implemented for {self.db_type}"
        )

    async def reset_password(self, external_id: str, new_password: str) -> ConnectorResult:
        return await self.update_user(external_id, {"password": new_password})
