"""
Connector Factory for IGA Platform.
Maps connector_type strings to connector classes and provides
a factory method to instantiate connectors from database records.
"""
from typing import Dict, Any, Optional, Type

from backend.connectors.base import BaseConnector


# ---------------------------------------------------------------------------
# Lazy imports — connectors may have optional heavy dependencies
# ---------------------------------------------------------------------------

def _import_connectors() -> Dict[str, Type[BaseConnector]]:
    registry: Dict[str, Type[BaseConnector]] = {}

    try:
        from backend.connectors.scim_connector import SCIMConnector
        registry["scim"] = SCIMConnector
    except ImportError:
        pass

    try:
        from backend.connectors.rest_connector import RESTConnector
        registry["rest"] = RESTConnector
    except ImportError:
        pass

    try:
        from backend.connectors.ldap_connector import LDAPConnector  # type: ignore
        registry["ldap"] = LDAPConnector
        registry["active_directory"] = LDAPConnector
    except ImportError:
        pass

    try:
        from backend.connectors.m365_connector import M365Connector
        registry["m365"] = M365Connector
        registry["microsoft365"] = M365Connector
        registry["azure_ad"] = M365Connector
    except ImportError:
        pass

    try:
        from backend.connectors.google_workspace_connector import GoogleWorkspaceConnector
        registry["google_workspace"] = GoogleWorkspaceConnector
        registry["gsuite"] = GoogleWorkspaceConnector
    except ImportError:
        pass

    try:
        from backend.connectors.salesforce_connector import SalesforceConnector
        registry["salesforce"] = SalesforceConnector
    except ImportError:
        pass

    try:
        from backend.connectors.servicenow_connector import ServiceNowConnector
        registry["servicenow"] = ServiceNowConnector
    except ImportError:
        pass

    try:
        from backend.connectors.slack_connector import SlackConnector
        registry["slack"] = SlackConnector
    except ImportError:
        pass

    try:
        from backend.connectors.database_connector import DatabaseConnector
        registry["database"] = DatabaseConnector
        registry["postgresql"] = DatabaseConnector
        registry["mysql"] = DatabaseConnector
    except ImportError:
        pass

    return registry


# Eagerly build the registry on module import
_CONNECTOR_REGISTRY: Dict[str, Type[BaseConnector]] = _import_connectors()


class ConnectorFactory:
    """
    Central factory for creating IGA connector instances.

    Usage::

        # From raw config dict
        connector = ConnectorFactory.create("scim", {"base_url": "...", "token": "..."})

        # From a database Connector ORM record
        connector = await ConnectorFactory.create_from_db(db_connector)
    """

    # ------------------------------------------------------------------
    # Registry helpers
    # ------------------------------------------------------------------

    @classmethod
    def get_registry(cls) -> Dict[str, Type[BaseConnector]]:
        """Return the full connector type → class mapping."""
        return dict(_CONNECTOR_REGISTRY)

    @classmethod
    def supported_types(cls) -> list:
        """Return a sorted list of supported connector type strings."""
        return sorted(_CONNECTOR_REGISTRY.keys())

    @classmethod
    def register(cls, connector_type: str, connector_class: Type[BaseConnector]) -> None:
        """Register a custom connector class at runtime."""
        _CONNECTOR_REGISTRY[connector_type.lower()] = connector_class

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def create(cls, connector_type: str, config: Dict[str, Any]) -> BaseConnector:
        """
        Instantiate a connector from a type string and a raw config dict.

        Parameters
        ----------
        connector_type : str
            One of the supported connector type strings (e.g. "scim", "m365").
        config : dict
            Configuration dictionary for the connector.

        Returns
        -------
        BaseConnector
            An initialised connector instance ready to use.

        Raises
        ------
        ValueError
            If connector_type is not registered.
        """
        key = connector_type.lower()
        connector_class = _CONNECTOR_REGISTRY.get(key)
        if connector_class is None:
            available = ", ".join(sorted(_CONNECTOR_REGISTRY.keys()))
            raise ValueError(
                f"Unsupported connector type: '{connector_type}'. "
                f"Available types: {available}"
            )
        return connector_class(config)

    @classmethod
    async def create_from_db(cls, db_connector) -> BaseConnector:
        """
        Instantiate a connector from a SQLAlchemy ``Connector`` ORM object.

        The ORM model is expected to have:
          - ``connector_type`` : str
          - ``config``         : dict  (plain config, may contain encrypted fields)
          - ``encrypted_config``: dict | None  (pre-encrypted override, merged if present)

        Parameters
        ----------
        db_connector : backend.models.connector.Connector
            Loaded ORM Connector record.

        Returns
        -------
        BaseConnector
            Fully initialised connector instance.
        """
        connector_type: str = db_connector.connector_type
        config: Dict[str, Any] = dict(db_connector.config or {})

        # Merge encrypted_config into config if the model has that column
        if hasattr(db_connector, "encrypted_config") and db_connector.encrypted_config:
            config.update(db_connector.encrypted_config)

        return cls.create(connector_type, config)

    @classmethod
    async def create_and_test(
        cls, connector_type: str, config: Dict[str, Any]
    ) -> tuple:
        """
        Create a connector and immediately test its connection.

        Returns
        -------
        tuple[BaseConnector, ConnectorResult]
        """
        from backend.connectors.base import ConnectorResult

        connector = cls.create(connector_type, config)
        result = await connector.test_connection()
        return connector, result
