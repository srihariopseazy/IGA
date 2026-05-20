from ldap3 import Server, Connection, ALL, NTLM, SIMPLE, SUBTREE, MODIFY_REPLACE, MODIFY_ADD, MODIFY_DELETE
from ldap3.core.exceptions import LDAPException
from backend.connectors.base import BaseConnector, ConnectorResult, UserAccount
from typing import Dict, Any, List, Optional
import logging


class LDAPConnector(BaseConnector):
    connector_type = "ldap"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.server_url = config.get("server_url")
        self.port = int(config.get("port", 389))
        self.use_ssl = config.get("use_ssl", False)
        self.use_starttls = config.get("use_starttls", False)
        self.bind_dn = config.get("bind_dn")
        self.bind_password = self._decrypt_config("bind_password")
        self.base_dn = config.get("base_dn")
        self.user_base_dn = config.get("user_base_dn") or self.base_dn
        self.group_base_dn = config.get("group_base_dn") or self.base_dn
        self.user_object_class = config.get("user_object_class", "person")
        self.user_id_attr = config.get("user_id_attr", "sAMAccountName")
        self.email_attr = config.get("email_attr", "mail")
        self.auth_type = config.get("auth_type", "SIMPLE")  # SIMPLE or NTLM

    def _get_connection(self) -> Connection:
        server = Server(self.server_url, port=self.port, use_ssl=self.use_ssl, get_info=ALL)
        auth = NTLM if self.auth_type == "NTLM" else SIMPLE
        conn = Connection(
            server,
            user=self.bind_dn,
            password=self.bind_password,
            authentication=auth,
            auto_bind=True,
        )
        if self.use_starttls and not self.use_ssl:
            conn.start_tls()
        return conn

    async def test_connection(self) -> ConnectorResult:
        try:
            conn = self._get_connection()
            conn.unbind()
            return ConnectorResult(success=True, data={"message": "Connection successful"})
        except LDAPException as e:
            return ConnectorResult(success=False, error=str(e))

    async def create_user(self, user: UserAccount) -> ConnectorResult:
        try:
            conn = self._get_connection()
            dn = f"cn={user.first_name} {user.last_name},{self.user_base_dn}"
            attributes = {
                "objectClass": ["top", "person", "organizationalPerson", "user"],
                "cn": f"{user.first_name} {user.last_name}",
                "givenName": user.first_name,
                "sn": user.last_name,
                "sAMAccountName": user.username,
                "mail": user.email,
                "userPrincipalName": f"{user.username}@{self._get_domain()}",
                "userAccountControl": "512",  # Normal enabled account
            }
            if user.attributes:
                attributes.update(user.attributes)

            success = conn.add(dn, attributes=attributes)
            conn.unbind()

            if success:
                return ConnectorResult(success=True, data={"dn": dn, "external_id": dn})
            else:
                return ConnectorResult(success=False, error=str(conn.result))
        except LDAPException as e:
            return ConnectorResult(success=False, error=str(e))

    async def update_user(self, external_id: str, attributes: Dict[str, Any]) -> ConnectorResult:
        try:
            conn = self._get_connection()
            changes = {k: [(MODIFY_REPLACE, [v])] for k, v in attributes.items()}
            success = conn.modify(external_id, changes)
            conn.unbind()
            return ConnectorResult(success=success, error=None if success else str(conn.result))
        except LDAPException as e:
            return ConnectorResult(success=False, error=str(e))

    async def delete_user(self, external_id: str) -> ConnectorResult:
        # In AD, we disable rather than delete
        return await self.disable_user(external_id)

    async def enable_user(self, external_id: str) -> ConnectorResult:
        try:
            conn = self._get_connection()
            # userAccountControl 512 = normal account enabled
            success = conn.modify(external_id, {"userAccountControl": [(MODIFY_REPLACE, [512])]})
            conn.unbind()
            return ConnectorResult(success=success)
        except LDAPException as e:
            return ConnectorResult(success=False, error=str(e))

    async def disable_user(self, external_id: str) -> ConnectorResult:
        try:
            conn = self._get_connection()
            # userAccountControl 514 = disabled account
            success = conn.modify(external_id, {"userAccountControl": [(MODIFY_REPLACE, [514])]})
            conn.unbind()
            return ConnectorResult(success=success)
        except LDAPException as e:
            return ConnectorResult(success=False, error=str(e))

    async def get_user(self, external_id: str) -> ConnectorResult:
        try:
            conn = self._get_connection()
            conn.search(
                search_base=self.user_base_dn,
                search_filter=f"(distinguishedName={external_id})",
                search_scope=SUBTREE,
                attributes=[
                    "cn", "givenName", "sn", "mail",
                    "sAMAccountName", "userAccountControl", "memberOf",
                ],
            )
            if conn.entries:
                entry = conn.entries[0]
                uac_val = str(entry.userAccountControl) if entry.userAccountControl else "0"
                user_data = {
                    "dn": entry.entry_dn,
                    "cn": str(entry.cn),
                    "email": str(entry.mail) if entry.mail else "",
                    "first_name": str(entry.givenName) if entry.givenName else "",
                    "last_name": str(entry.sn) if entry.sn else "",
                    "username": str(entry.sAMAccountName) if entry.sAMAccountName else "",
                    "groups": [str(g) for g in entry.memberOf] if entry.memberOf else [],
                    "is_active": (int(uac_val) & 2) == 0 if uac_val.isdigit() else False,
                }
                conn.unbind()
                return ConnectorResult(success=True, data=user_data)
            conn.unbind()
            return ConnectorResult(success=False, error="User not found")
        except LDAPException as e:
            return ConnectorResult(success=False, error=str(e))

    async def list_users(self, filter: str = None) -> ConnectorResult:
        try:
            conn = self._get_connection()
            ldap_filter = (
                filter
                or f"(&(objectClass={self.user_object_class})(!(userAccountControl:1.2.840.113556.1.4.803:=2)))"
            )
            conn.search(
                search_base=self.user_base_dn,
                search_filter=ldap_filter,
                search_scope=SUBTREE,
                attributes=["cn", "givenName", "sn", "mail", "sAMAccountName", "userAccountControl"],
                paged_size=500,
            )
            users = []
            for entry in conn.entries:
                users.append(
                    {
                        "dn": entry.entry_dn,
                        "email": str(entry.mail) if entry.mail else "",
                        "first_name": str(entry.givenName) if entry.givenName else "",
                        "last_name": str(entry.sn) if entry.sn else "",
                        "username": str(entry.sAMAccountName) if entry.sAMAccountName else "",
                        "is_active": True,
                    }
                )
            conn.unbind()
            return ConnectorResult(success=True, data={"users": users, "count": len(users)})
        except LDAPException as e:
            return ConnectorResult(success=False, error=str(e))

    async def add_to_group(self, user_dn: str, group_dn: str) -> ConnectorResult:
        try:
            conn = self._get_connection()
            success = conn.modify(group_dn, {"member": [(MODIFY_ADD, [user_dn])]})
            conn.unbind()
            return ConnectorResult(success=success, error=None if success else str(conn.result))
        except LDAPException as e:
            return ConnectorResult(success=False, error=str(e))

    async def remove_from_group(self, user_dn: str, group_dn: str) -> ConnectorResult:
        try:
            conn = self._get_connection()
            success = conn.modify(group_dn, {"member": [(MODIFY_DELETE, [user_dn])]})
            conn.unbind()
            return ConnectorResult(success=success, error=None if success else str(conn.result))
        except LDAPException as e:
            return ConnectorResult(success=False, error=str(e))

    async def reset_password(self, external_id: str, new_password: str) -> ConnectorResult:
        """Reset AD user password using unicodePwd attribute."""
        try:
            conn = self._get_connection()
            import struct

            # AD requires password encoded as UTF-16LE, wrapped in quotes
            unicode_pass = f'"{new_password}"'.encode("utf-16-le")
            success = conn.modify(external_id, {"unicodePwd": [(MODIFY_REPLACE, [unicode_pass])]})
            conn.unbind()
            return ConnectorResult(success=success, error=None if success else str(conn.result))
        except LDAPException as e:
            return ConnectorResult(success=False, error=str(e))

    async def sync_users(self) -> Dict[str, Any]:
        result = await self.list_users()
        if not result.success:
            return {"success": False, "error": result.error}
        return {
            "success": True,
            "users": result.data["users"],
            "count": result.data["count"],
        }

    def _get_domain(self) -> str:
        """Extract domain from base_dn (e.g., 'dc=example,dc=com' -> 'example.com')."""
        parts = [p.split("=")[1] for p in self.base_dn.split(",") if p.lower().startswith("dc=")]
        return ".".join(parts)
