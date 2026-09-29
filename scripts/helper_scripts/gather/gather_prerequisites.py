###############################################################################
#
# Licensed Materials - Property of IBM
#
# (C) Copyright IBM Corp. 2024. All Rights Reserved.
#
# US Government Users Restricted Rights - Use, duplication or
# disclosure restricted by GSA ADP Schedule Contract with IBM Corp.
#
###############################################################################

import sys
from enum import Enum
from urllib.parse import urlparse

import questionary
import requests
from questionary import Style
from rich import print
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..utilities.kubernetes_utilites import KubernetesUtilities
from ..utilities.questionary_utils import safe_questionary_prompt

# ── Shared questionary style ──────────────────────────────────────────────────
_QS = Style([
    ("qmark",       "fg:ansibrightcyan bold"),
    ("question",    "bold"),
    ("answer",      "fg:ansibrightcyan bold"),
    ("pointer",     "fg:ansibrightcyan bold"),
    ("selected",    "fg:ansicyan"),
    ("separator",   "fg:ansiblack"),
    ("instruction", "fg:ansiblack"),
])


def _info_panel(title: str, body: str | Text, border: str = "cyan") -> None:
    """Print a cyan info Panel above a questionary prompt."""
    if isinstance(body, str):
        body = Text.from_markup(body)
    print(Panel(body, title=f"[bold cyan]{title}[/bold cyan]",
                border_style=border, padding=(1, 2)))
    print()


def _kv_panel(title: str, rows: list[tuple[str, str]], border: str = "cyan") -> None:
    """Print a key-value info panel built from a list of (label, value) pairs."""
    tbl = Table.grid(padding=(0, 2))
    tbl.add_column(style="cyan", justify="left")
    tbl.add_column(style="white")
    for label, value in rows:
        tbl.add_row(label, value)
    print(Panel(tbl, title=f"[bold cyan]{title}[/bold cyan]",
                border_style=border, padding=(1, 2)))
    print()

requests.packages.urllib3.disable_warnings()


# create a class to gather all deployment options from the user for the prerequisite scripts
class GatherPrereqOptions:
    # Inner Class to take care of CAS version.
    class Version:
        """
        Class to store CAS version details
        Attributes:
            cas_version (CASVersion): Enum representing the CAS version
        """
        CASVersion = Enum(
            value='CASVersion',
            names=[("1.0.0", 1)]
        )

        def __init__(self, cas_version: CASVersion):
            self._cas_version = cas_version

    # Inner class to store Vector Database details
    class VectorDatabase:
        """
        Class to store Vector Database details
        Attributes:
            vector_db_label (str): Label for the vector database (e.g., VECTORDB,
            VECTORDB1, VECTORDB2, etc.)
            vector_db_auth_type (str): Authentication type for the vector database
            (e.g., BASICAUTH, OIDC)
            ssl_enabled (bool): Flag to indicate if SSL is enabled for the vector
            database connection
        """
        def __init__(self,vector_db_label: str,vector_db_auth_type: str, ssl_enabled: bool = False):
            self._vector_db_label = vector_db_label
            self._vector_db_auth_type = vector_db_auth_type
            self._vector_db_ssl_enabled = ssl_enabled

        @property
        def vector_db_ssl_enabled(self):
            return self._vector_db_ssl_enabled

        @property
        def get_db_auth_type(self):
            return self._vector_db_auth_type

        @property
        def get_db_label(self):
            return self._vector_db_label

    # Create an inner class to gather ldap info from the user
    class Idp:
        """
        Class to store IDP details
        Attributes:
            discovery_url (str): URL for the IDP discovery endpoint
            discovery_enabled (bool): Flag to indicate if discovery is enabled for
            the IDP
            idp_id (str): IDP identifier (e.g., idp, idp1, idp2, etc.)
            validation_method (str): Method used for token validation (e.g.,
            introspect, userinfo)
            introspect_url (str): URL for the introspection endpoint
            userinfo_url (str): URL for the userinfo endpoint
            token_url (str): URL for the token endpoint
            revoke_url (str): URL for the revocation endpoint
            issuer (str): Issuer identifier
            client_id (str): Client identifier
            client_secret (str): Client secret
            jwks_url (str): URL for the JWKS endpoint
            user_identifier (str): User identifier claim (e.g., sub, email,
            preferred_username)
            unique_user_identifier (str): Unique user identifier claim (e.g., sub)
            user_identifier_to_sub (str): Mapping of user identifier to sub claim
            ssl_enabled (bool): Flag to indicate if SSL is enabled for the IDP
            connection
        Methods:
            parse_discovery_url(): Parses the discovery URL to retrieve IDP
            configuration
            display(): Displays the IDP details
            to_dict(): Returns the IDP details as a dictionary
        """
        def __init__(self, discovery_enabled: bool, idp_id: str = None, discovery_url: str = None):
            self._discovery_url = discovery_url
            self._discovery_enabled = discovery_enabled
            self._idp_id = idp_id
            self._validation_method = "introspect"
            self._introspect_url = "<Required>"
            self._userinfo_url = "<Required>"
            self._token_url = "<Required>"
            self._revoke_url = "<Required>"
            self._issuer = "<Required>"
            self._client_id = "<Required>"
            self._client_secret = "<Required>"
            self._jwks_url = "<Required>"
            self._user_identifier = "sub"
            self._unique_user_identifier = "sub"
            self._user_identifier_to_sub = "sub"
            self._ssl_enabled = True

        # Create a function to parse the json return from discovery url
        def parse_discovery_url(self):
            try:
                # Create a variable to hold the url
                url = self._discovery_url

                # Check if the url is valid
                if url is None:
                    return False
                else:
                    if url.endswith(".well-known/openid-configuration"):
                        # Create a variable to hold the json
                        json = requests.get(url, timeout=5, verify=False).json()

                        # Check if the json is valid
                        if json is None:
                            return False
                        else:
                            # Check if the json contains the required fields
                            if "introspection_endpoint" in json:
                                self._introspect_url = json["introspection_endpoint"]
                                self._validation_method = "introspect"

                                if "preferred_username" in json["claims_supported"]:
                                    self._user_identifier = "preferred_username"

                            elif "userinfo_endpoint" in json:
                                self._userinfo_url = json["userinfo_endpoint"]
                                self._validation_method = "userinfo"

                                if "email" in json["claims_supported"]:
                                    self._user_identifier = "email"

                            else:
                                return False

                            if "token_endpoint" in json:
                                self._token_url = json["token_endpoint"]

                            if "revocation_endpoint" in json:
                                self._revoke_url = json["revocation_endpoint"]

                            if "issuer" in json:
                                self._issuer = json["issuer"]

                            if "jwks_uri" in json:
                                self._jwks_url = json["jwks_uri"]

                            # Check if the discovery url is https scheme
                            if urlparse(url).scheme == "https":
                                self._ssl_enabled = True
                            else:
                                self._ssl_enabled = False

                            return True

                    else:
                        return False
            except Exception as e:
                print(f"Exception from parse_discovery_url function - {str(e)}")
                return False

        # Create a function to display the ldap info
        def display(self):
            print("Discovery URL:", self._discovery_url)
            print("Discovery Enabled:", self._discovery_enabled)
            print("IDP ID:", self._idp_id)

        # Create a function to return the ldap info as a dictionary
        def to_dict(self):
            return {
                "discovery_url": self._discovery_url,
                "discovery_enabled": self._discovery_enabled,
                "id": self._idp_id,
                "validation_method": self._validation_method,
                "introspect_url": self._introspect_url,
                "userinfo_url": self._userinfo_url,
                "jwks_url": self._jwks_url,
                "token_url": self._token_url,
                "revoke_url": self._revoke_url,
                "issuer": self._issuer,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "user_identifier": self._user_identifier,
                "unique_user_identifier": self._unique_user_identifier,
                "user_identifier_to_sub": self._user_identifier_to_sub,
                "ssl_enabled": self._ssl_enabled
            }



    class AuthType(Enum):
        '''
        Enum to represent the authentication type
        '''
        BASICAUTH = 1
        OIDC = 2

    # Create an enum for all platform types
    class Platform(Enum):
        '''
        Enum to represent the platform type
        '''
        OCP = 1
        other = 2

    class LicenseModel(Enum):
        CCX = 1
        cp4ba = 2

    class AIProviderType(Enum):
        '''
        Enum to represent the AI Provider type
        '''
        WATSONX_SAAS = 1
        WATSONX_LIGHTWEIGHT = 2
        MODEL_GATEWAY = 3


    def __init__(self, logger, console):

        self._idp_info = []
        self._idp_number = 0
        self._ai_provider_number = 1
        self._vector_database_number = 1
        self._vector_database_details = []
        self._platform = self.Platform(1).name
        self._license_model = "fncm"
        self._ingress = False
        self._logger = logger
        self._console = console
        self._ssl_directory_list = []
        self._cas_version = "1.0.0"
        self._np_support = False
        self._fips_support = False
        self._enable_admin_access = False
        self._auth_type = self.AuthType(1).name
        self._namespace = None
        self._current_namespace = None
        self._script_type = "gather"
        self._k = KubernetesUtilities(self._logger)
        self._ai_provider_type = "WATSONX_SAAS"
        self._model_gateway_ssl_enabled = False
        self._create_opensearch_cluster = False
        self._opensearch_storage_class = "<Required>"
        self._opensearch_block_storage_class = "<Required>"
        self._opensearch_cluster_hostname = "<Required>"
        self._opensearch_admin_password = "<Required>"
        self._opensearch_genai_password = "<Required>"

    # Create a function to gather all deployment options from the user
    @property
    def license_model(self):
        return self._license_model

    @property
    def namespace(self):
        return self._namespace

    @property
    def cas_version(self):
        return self._cas_version

    @property
    def np_support(self):
        return self._np_support

    @property
    def fips_support(self):
        return self._fips_support


    @property
    def vector_database_number(self):
        return self._vector_database_number


    @property
    def ai_provider_number(self):
        return self._ai_provider_number


    @property
    def auth_type(self):
        return self._auth_type

    @auth_type.setter
    def auth_type(self, value):
        self._auth_type = value


    @property
    def idp_info(self):
        return self._idp_info

    @idp_info.setter
    def idp_info(self, value):
        self._idp_info = value

    @property
    def idp_number(self):
        return self._idp_number

    @property
    def vector_db_details(self):
        return self._vector_database_details


    @property
    def platform(self):
        return self._platform

    @platform.setter
    def platform(self, value):
        self._platform = value

    @property
    def ingress(self):
        return self._ingress

    @ingress.setter
    def ingress(self, value):
        self._ingress = value

    # Create a method to return the ssl directory list
    @property
    def ssl_directory_list(self):
        return self._ssl_directory_list

    # @property
    # def vector_db_ssl_directory_dict(self):
    #     return self._vector_db_ssl_directory_dict

    @property
    def enable_admin_access(self):
        return self._enable_admin_access

    @property
    def ai_provider_type(self):
        return self._ai_provider_type

    @ai_provider_type.setter
    def ai_provider_type(self, value):
        self._ai_provider_type = value

    @property
    def model_gateway_ssl_enabled(self):
        return self._model_gateway_ssl_enabled

    @model_gateway_ssl_enabled.setter
    def model_gateway_ssl_enabled(self, value):
        self._model_gateway_ssl_enabled = value

    @property
    def create_opensearch_cluster(self):
        return self._create_opensearch_cluster

    @property
    def opensearch_storage_class(self):
        return self._opensearch_storage_class

    @property
    def opensearch_block_storage_class(self):
        return self._opensearch_block_storage_class

    @property
    def opensearch_cluster_hostname(self):
        return self._opensearch_cluster_hostname

    @property
    def opensearch_admin_password(self):
        return self._opensearch_admin_password

    @property
    def opensearch_genai_password(self):
        return self._opensearch_genai_password

    def collect_ai_provider_type(self):
        """Collect AI Provider type from the user via questionary select."""
        try:
            _info_panel(
                "🤖  AI Provider Type",
                "[bold white]IBM Content Assistant supports three AI provider modes:[/bold white]\n\n"
                "[bold cyan]WatsonX SaaS[/bold cyan]  — IBM-hosted cloud service\n"
                "  Requires: [dim]API Key, Space ID, and WatsonX URL[/dim]\n\n"
                "[bold cyan]WatsonX Lightweight[/bold cyan]  — self-managed, in-cluster deployment\n"
                "  Requires: [dim]API Key, Username, and deployment URL[/dim]\n\n"
                "[bold cyan]Model Gateway[/bold cyan]  — shared gateway with per-tenant API keys\n"
                "  Requires: [dim]Gateway URL, SSL setting, and one API Key per tenant[/dim]\n\n"
                "[dim]Use SaaS for IBM Cloud-hosted models. Use Lightweight for an on-premises or CNCF deployment.\n"
                "Use Model Gateway when multiple tenants share a single gateway endpoint.[/dim]",
            )

            result = safe_questionary_prompt(
                questionary.select,
                message="Select AI Provider type:",
                choices=[
                    questionary.Choice("WatsonX SaaS  (API Key + Space ID + URL)",
                                       value="WATSONX_SAAS"),
                    questionary.Choice("WatsonX Lightweight  (API Key + Username + URL)",
                                       value="WATSONX_LIGHTWEIGHT"),
                    questionary.Choice("Model Gateway  (API Key per tenant + shared URL)",
                                       value="MODEL_GATEWAY"),
                ],
                style=_QS,
            )
            self._ai_provider_type = result
            self._logger.info(f"AI Provider type selected: {self._ai_provider_type}")

        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in collect_ai_provider_type function - {str(e)}")

    def collect_model_gateway_details(self):
        """Collect ModelGateway SSL preference from the user."""
        try:
            _info_panel(
                "🌐  Model Gateway Configuration",
                "[bold white]Model Gateway uses a gateway URL and an API key.[/bold white]\n\n"
                "[dim]•[/dim] API key is stored as a Kubernetes secret\n"
                "[dim]•[/dim] URL and API key remain as [bold]<Required>[/bold] placeholders — fill them in after generation\n"
                "[dim]•[/dim] SSL encrypts traffic between the operator and the gateway endpoint",
            )

            # Prompt for SSL
            ssl_enabled = safe_questionary_prompt(
                questionary.confirm,
                message="Enable SSL for the Model Gateway connection?",
                default=True,
                style=_QS,
            )
            self._model_gateway_ssl_enabled = ssl_enabled
            self._logger.info(f"Model Gateway SSL enabled: {self._model_gateway_ssl_enabled}")

        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in collect_model_gateway_details function - {str(e)}")

    def collect_namespace(self, namespace=None):
        """Collect and validate a Kubernetes namespace via questionary text prompt."""
        try:
            self._logger.info("Gathering namespace information")

            if namespace is None:
                try:
                    self._current_namespace = self._k.current_namespace
                    self._logger.info(
                        f"Current namespace from kubeconfig: {self._current_namespace}")
                except Exception:
                    self._current_namespace = None
                    self._logger.info("Could not detect current namespace from kubeconfig")

            if self._platform in ["OCP"]:
                invalid_namespaces = [
                    "services", "default", "calico-system",
                    "ibm-cert-store", "ibm-observe", "ibm-system",
                    "ibm-odf-validation-webhook",
                ]
                invalid_namespace_to_start_with = ["openshift-", "kube-"]
            else:
                invalid_namespaces = ["services", "default", "calico-system"]
                invalid_namespace_to_start_with = ["kube-"]

            # Build context panel — only shown in interactive mode
            ctx_rows = [
                ("Rules:", "lowercase letters, digits, and hyphens only"),
                ("Max length:", "63 characters"),
                ("Cannot start with:", ", ".join(invalid_namespace_to_start_with)),
                ("Reserved names:", ", ".join(invalid_namespaces[:3]) + " …"),
            ]
            if self._current_namespace:
                ctx_rows.insert(0, ("Detected:", self._current_namespace))

            while True:
                if namespace is None:
                    _kv_panel("☸  Namespace", ctx_rows)
                    answer = safe_questionary_prompt(
                        questionary.text,
                        message="Enter target namespace:",
                        default=self._current_namespace or "",
                        style=_QS,
                    )
                    answer = answer.strip()

                    # Inline validation — show red panel and re-prompt
                    def _invalid(msg: str) -> None:
                        print()
                        print(Panel.fit(
                            f"[bold red]✗[/bold red]  {msg}",
                            border_style="red",
                        ))
                        print()

                    if answer == "":
                        _invalid("Namespace cannot be empty.")
                        continue
                    if any(answer == v for v in invalid_namespaces):
                        _invalid(f"[bold yellow]{answer}[/bold yellow] is a reserved namespace.")
                        continue
                    if any(answer.startswith(v) for v in invalid_namespace_to_start_with):
                        _invalid(f"Namespace cannot start with [bold yellow]{answer.split('-')[0]}-[/bold yellow]")
                        continue
                    if answer.isnumeric():
                        _invalid("Namespace cannot be all digits.")
                        continue
                    if " " in answer:
                        _invalid("Namespace cannot contain spaces — use [bold cyan]-[/bold cyan] instead.")
                        continue
                    if any(c.isupper() for c in answer):
                        _invalid("Namespace must be lowercase.")
                        continue
                    if "_" in answer:
                        _invalid("Namespace cannot contain [bold cyan]_[/bold cyan] — use [bold cyan]-[/bold cyan] instead.")
                        continue

                    if self._script_type != "deploy":
                        namespace_exists = self._k.check_namespace_exists(namespace=answer)
                        if not namespace_exists:
                            _invalid(
                                f"Namespace [bold yellow]{answer}[/bold yellow] does not exist in the cluster.")
                            continue

                else:
                    # Silent mode — validate once and exit on any error
                    answer = namespace.strip()
                    if self._script_type != "deploy":
                        self._logger.info(f"Checking if namespace: {answer} exists.")
                        if not self._k.check_namespace_exists(namespace=answer):
                            self._logger.error(f"Namespace '{answer}' does not exist.")
                            print(Panel.fit(
                                f"[bold red]✗[/bold red]  Namespace [bold yellow]{answer}[/bold yellow] "
                                "does not exist.",
                                border_style="red",
                            ))
                            sys.exit(1)

                self._namespace = answer
                self._logger.info(f"Namespace entered: {self._namespace}")
                break

        except Exception as e:
            self._logger.exception(
                f"Exception from gathering deployment details in collect namespace function - {str(e)}")



    def collect_fips_support(self):
        """Ask whether to enable FIPS compliance mode."""
        try:
            _info_panel(
                "🔐  FIPS Compliance",
                "[bold white]FIPS mode enforces federal cryptographic standards.[/bold white]\n\n"
                "[dim]•[/dim] Sets [cyan]enable_fips: true[/cyan] in the generated CR\n\n"
                "[dim]Enable only if your organisation mandates FIPS compliance.[/dim]",
            )

            result = safe_questionary_prompt(
                questionary.confirm,
                message="Enable FIPS compliance mode?",
                default=False,
                style=_QS,
            )
            if result:
                self._fips_support = True

        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in collect_fips_support function - {str(e)}")

    def collect_networkpolicy_info(self):
        """Ask whether to generate Network Policy templates."""
        try:
            _info_panel(
                "🔒  Network Policies",
                "[bold white]Network Policies control pod-level traffic in your cluster.[/bold white]\n\n"
                "[dim]•[/dim] Policies are [bold]not[/bold] applied automatically — they are generated as templates\n"
                "[dim]•[/dim] Templates cover both [cyan]ingress[/cyan] and [cyan]egress[/cyan] directions\n"
                "[dim]•[/dim] Apply them manually with [bold cyan]kubectl apply -f[/bold cyan] after reviewing\n\n"
                "[dim]Recommended for production environments that enforce network isolation.[/dim]",
            )

            result = safe_questionary_prompt(
                questionary.confirm,
                message="Generate Network Policy templates for this deployment?",
                default=False,
                style=_QS,
            )
            if result:
                self._np_support = True

        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in collect_networkpolicy_info function - {str(e)}")

    def collect_content_assistant_admin_access(self):
        """Ask whether to enable the IBM Content Assistant CLI admin access."""
        try:
            _info_panel(
                "🖥  IBM Content Assistant CLI",
                "[bold white]Optionally enable CLI-based administration of IBM Content Assistant.[/bold white]\n\n"
                "[dim]•[/dim] The CLI is [bold]disabled[/bold] by default\n"
                "[dim]•[/dim] On [cyan]OCP[/cyan]: exposed via an OpenShift [bold]Route[/bold]\n"
                "[dim]•[/dim] On [cyan]CNCF[/cyan]: exposed via a Kubernetes [bold]Ingress[/bold]\n"
                "[dim]•[/dim] A [bold]private key[/bold] and [bold]passphrase[/bold] are auto-generated for secure access\n\n"
                "[dim]Enable only if you need programmatic or scripted administration of Content Assistant.[/dim]",
            )

            result = safe_questionary_prompt(
                questionary.confirm,
                message="Enable IBM Content Assistant CLI admin access?",
                default=False,
                style=_QS,
            )
            if result:
                self._enable_admin_access = True

        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in collect_content_assistant_admin_access function - {str(e)}")


    # Create a function to check if the dsicovery url is valid
    def check_discovery_url(self, url: str):
        try:

            # Check if the url is valid
            if url is None:
                return False
            else:
                if url.endswith(".well-known/openid-configuration"):
                    return True
                else:
                    return False
        except Exception as e:
            print(f"Exception from check_discovery_url function - {str(e)}")
            return False

    def collect_vector_db_number(self):
        """Ask how many Vector Databases to configure."""
        try:
            _info_panel(
                "🗄  Vector Databases",
                "[bold white]IBM Content Assistant requires at least one Vector Database.[/bold white]\n\n"
                "[dim]•[/dim] Each Vector Database stores AI-generated embeddings for document search\n"
                "[dim]•[/dim] Multiple databases are supported for high-availability setups\n"
                "[dim]•[/dim] At least [bold cyan]1[/bold cyan] must be configured\n\n"
                "[dim]For most deployments, a single Vector Database is sufficient.[/dim]",
            )

            while True:
                raw = safe_questionary_prompt(
                    questionary.text,
                    message="Number of Vector Databases to configure:",
                    default="1",
                    style=_QS,
                    validate=lambda v: (
                        True if v.strip().isdigit() and int(v.strip()) >= 1
                        else "Enter a whole number ≥ 1"
                    ),
                )
                self._vector_database_number = int(raw.strip())
                break

        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in collect_vector_db_number function - {str(e)}")

    def collect_auth_type(self, db_label: str = "VECTORDB") -> str:
        """Collect Vector Database authentication type via questionary select."""
        try:
            _info_panel(
                f"🔑  {db_label} — Authentication Type",
                "[bold white]Choose how IBM Content Assistant authenticates to the Vector Database.[/bold white]\n\n"
                "[bold cyan]Basic Authentication[/bold cyan]  (BASICAUTH)\n"
                "  [dim]Standard username + password — simplest to configure[/dim]\n\n"
                "[bold cyan]OpenID Connect[/bold cyan]  (OIDC)\n"
                "  [dim]Token-based auth via an OIDC provider — required for enterprise SSO setups[/dim]\n"
                "  [dim]Selecting OIDC will also prompt for an OIDC SSL certificate[/dim]",
            )

            result = safe_questionary_prompt(
                questionary.select,
                message=f"Authentication type for {db_label}:",
                choices=[
                    questionary.Choice("Basic Authentication  (username + password)",
                                       value="BASICAUTH"),
                    questionary.Choice("OpenID Connect  (OIDC)",
                                       value="OIDC"),
                ],
                style=_QS,
            )
            return result

        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in collect_auth_type function - {str(e)}")
            return "BASICAUTH"

    def collect_vector_ssl_info(self) -> bool:
        """Ask whether to enable SSL for the Vector Database connection."""
        _info_panel(
            "🔒  Vector Database — SSL / TLS",
            "[bold white]SSL encrypts traffic between IBM Content Assistant and the Vector Database.[/bold white]\n\n"
            "[dim]•[/dim] [bold]Strongly recommended[/bold] when the database is hosted externally or in a different network\n"
            "[dim]•[/dim] If [cyan]OIDC[/cyan] was chosen as auth type, the OIDC provider connection is also secured\n"
            "[dim]•[/dim] You will need to provide the PEM certificate file for the database's CA\n\n"
            "[dim]Enable SSL unless the Vector Database is co-located on the same trusted internal network.[/dim]",
        )
        return safe_questionary_prompt(
            questionary.confirm,
            message="Enable SSL for this Vector Database connection?",
            default=True,
            style=_QS,
        )

    # function to collect the vector db details
    def collect_vector_db_details(self):
        # For now we only have 1 vector DB support
        #self.collect_vector_db_number()
        for index in range(self._vector_database_number):
            db_label = f"VECTORDB{index+1}" if index > 0 else "VECTORDB"
            auth_type = self.collect_auth_type(db_label=db_label)
            ssl_enabled = self.collect_vector_ssl_info()
            vector_db_instance = self.VectorDatabase(vector_db_label=db_label, vector_db_auth_type=auth_type, ssl_enabled=ssl_enabled)

            if ssl_enabled:
                self._ssl_directory_list.append(f"{db_label.lower()}")
                if auth_type.lower() == "oidc":
                    self._ssl_directory_list.append(f"{db_label.lower()}-oidc")

            self._vector_database_details.append(vector_db_instance)

    def collect_license_model(self, version_data: dict) -> None:
        """Collect license model selection and obtain explicit license acceptance."""
        try:
            version = version_data.get("VERSION", "1.0.0")
            self._cas_version = version
            display = version_data.get("DISPLAY", version)

            # ── Step 1: version + license model selection ─────────────────────
            _info_panel(
                "📄  License & Version",
                f"[bold white]Select the license model for your IBM Content Assistant deployment.[/bold white]\n\n"
                f"[cyan]Detected version:[/cyan]  [bold green]{display}[/bold green]\n\n"
                f"[bold cyan]Essentials[/bold cyan]  — IBM Content Cortex Essentials license\n"
                f"[bold cyan]Premium[/bold cyan]     — IBM Content Cortex Premium license\n"
                f"[bold cyan]CP4BA[/bold cyan]       — IBM Cloud Pak for Business Automation bundle\n"
                f"  [dim](includes OpenSearch operator support)[/dim]",
            )

            result = safe_questionary_prompt(
                questionary.select,
                message="Select a License Type:",
                choices=[
                    questionary.Choice("Essentials", value="fncm"),
                    questionary.Choice("Premium",    value="fncm"),
                    questionary.Choice("CP4BA",      value="cp4ba"),
                ],
                style=_QS,
            )
            self._license_model = result

            # ── Step 2: license review ────────────────────────────────────────
            license_info = Text()
            license_info.append("🏷️ License Type Selection\n\n", style="bold cyan")
            license_info.append("Choose the license model that matches your entitlement:\n\n", style="white")
            license_info.append("  • ", style="cyan")
            license_info.append("Content Cortex Essentials", style="bold green")
            license_info.append(" - IBM Content Cortex Essentials license\n", style="white")
            license_info.append("  • ", style="cyan")
            license_info.append("Content Cortex Premium", style="bold green")
            license_info.append(" - IBM Content Cortex Premium license\n", style="white")
            license_info.append("  • ", style="cyan")
            license_info.append("CP4BA", style="bold green")
            license_info.append(" - Cloud Pak for Business Automation license\n\n", style="white")

            license_info.append("📄 ", style="bold cyan")
            license_info.append("IBM Content Assistant:  ", style="bold white")
            license_info.append("https://ibm.biz/CPE_CCX_License_26_0_0\n", style="cyan")
            license_info.append("📄 ", style="bold cyan")
            license_info.append("Software Notices:    ", style="bold white")
            license_info.append("https://ibm.biz/CAS_Notices_1_0_0\n", style="cyan")
            if result == "cp4ba":
                license_info.append("📄 ", style="bold cyan")
                license_info.append("CP4BA License:       ", style="bold white")
                license_info.append("https://ibm.biz/cp4ba_license_2600\n", style="cyan")
                license_info.append("📄 ", style="bold cyan")
                license_info.append("CP4BA Reserved:      ", style="bold white")
                license_info.append("https://ibm.biz/cp4ba-reserved-license-2600\n", style="cyan")

            license_info.append("\n⚠ ", style="bold yellow")
            license_info.append(
                "By accepting, you agree to comply with all license terms and conditions.\n"
                "Data collection is enabled by default — see the License Information document for details.",
                style="dim white",
            )

            print(Panel(
                license_info,
                title="[bold yellow]⚠  License Agreement Required[/bold yellow]",
                border_style="yellow",
                padding=(1, 2),
            ))
            print()

            accepted = safe_questionary_prompt(
                questionary.confirm,
                message="Do you accept the International Program License Agreement?",
                default=False,
                style=_QS,
            )

            if not accepted:
                print()
                print(Panel.fit(
                    "[bold red]✗[/bold red]  License not accepted — deployment cancelled.",
                    border_style="red",
                ))
                sys.exit(1)

            print()
            print(Panel.fit(
                "[bold green]✓[/bold green]  License Agreement accepted.",
                border_style="green",
            ))

        except SystemExit:
            raise
        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in collect_license_model function - {str(e)}")


    def collect_opensearch_cluster_option(self) -> None:
        """
        Ask whether to provision an OpenSearch cluster via the CP4BA operator.
        Only called when CP4BA license is selected.
        """
        try:
            _info_panel(
                "🔍  OpenSearch Cluster (CP4BA)",
                "[bold white]IBM Content Assistant can use OpenSearch as its Vector Database.[/bold white]\n\n"
                "[dim]•[/dim] The [cyan]OpenSearch Operator[/cyan] is already included with your CP4BA deployment\n"
                "[dim]•[/dim] Selecting [bold]Yes[/bold] generates OpenSearch cluster YAML manifests for your namespace\n"
                "[dim]•[/dim] Cluster storage classes and hostname are configured in the property file\n"
                "[dim]•[/dim] Selecting [bold]No[/bold] lets you configure an [cyan]external[/cyan] Vector Database instead\n\n"
                "[dim]Recommended for CP4BA deployments that don't already have a Vector Database.[/dim]",
            )

            self._create_opensearch_cluster = safe_questionary_prompt(
                questionary.confirm,
                message="Use OpenSearch (CP4BA) as your Vector Database?",
                default=True,
                style=_QS,
            )

            # In both cases, cluster details are sourced from the property file
            self._opensearch_storage_class = None
            self._opensearch_block_storage_class = None
            self._opensearch_cluster_hostname = None
            self._opensearch_admin_password = None
            self._opensearch_genai_password = None

            if self._create_opensearch_cluster:
                print()
                print(Panel.fit(
                    "[bold green]✓[/bold green]  OpenSearch cluster will be configured as your Vector Database.\n"
                    "  [dim]Review and update the property file before running [bold cyan]generate[/bold cyan].[/dim]",
                    border_style="green",
                ))

        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in collect_opensearch_cluster_option function - {str(e)}")


    def collect_platform_ingress(self) -> None:
        """Collect target platform type and, for CNCF, whether to enable Ingress."""
        try:
            _info_panel(
                "☸  Platform",
                "[bold white]Select the Kubernetes platform where IBM Content Assistant will be deployed.[/bold white]\n\n"
                "[bold cyan]OCP[/bold cyan]  — Red Hat OpenShift Container Platform\n"
                "  [dim]Routes are used for external access — no Ingress configuration needed[/dim]\n\n"
                "[bold cyan]CNCF[/bold cyan]  — Standard Kubernetes (AKS, EKS, GKE, vanilla K8s)\n"
                "  [dim]You will be asked whether to enable Kubernetes Ingress for external access[/dim]",
            )

            result = safe_questionary_prompt(
                questionary.select,
                message="Select your deployment platform:",
                choices=[
                    questionary.Choice("OCP   — Red Hat OpenShift", value="OCP"),
                    questionary.Choice("CNCF  — Standard Kubernetes", value="other"),
                ],
                style=_QS,
            )
            self._platform = result

            if self._platform == "other":
                _info_panel(
                    "🌐  Kubernetes Ingress",
                    "[bold white]On CNCF clusters, IBM Content Assistant uses an Ingress resource for external access.[/bold white]\n\n"
                    "[dim]•[/dim] [bold]Enable[/bold] if your cluster has an Ingress controller (nginx, traefik, AWS ALB, etc.)\n"
                    "[dim]•[/dim] [bold]Disable[/bold] if you will expose services via LoadBalancer or NodePort instead\n\n"
                    "[dim]Most managed Kubernetes clusters (EKS, AKS, GKE) support Ingress by default.[/dim]",
                )
                self._ingress = safe_questionary_prompt(
                    questionary.confirm,
                    message="Enable Ingress for external access?",
                    default=True,
                    style=_QS,
                )

        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in collect_platform_ingress function - {str(e)}")

    # Create a function to gather idp_number from user
    def collect_idp_number(self):
        try:
            if self._auth_type == "SCIM_IDP":
                self._idp_number = 1
                self._scim_number = 1
                self._ssl_directory_list.append("scim")
            else:
                _info_panel(
                    "🔐  Identity Providers",
                    "[bold white]Configure how many Identity Providers (IDPs) to set up.[/bold white]\n\n"
                    "[dim]•[/dim] Each IDP provides an OIDC / token-based authentication source\n"
                    "[dim]•[/dim] Most deployments use a single IDP\n"
                    "[dim]•[/dim] Provide at least [bold cyan]1[/bold cyan]\n\n"
                    "[dim]For most setups, enter [bold cyan]1[/bold cyan] unless you are federating multiple identity providers.[/dim]",
                )
                raw = safe_questionary_prompt(
                    questionary.text,
                    message="How many Identity Providers do you want to configure?",
                    default="1",
                    style=_QS,
                    validate=lambda v: (
                        True if v.strip().isdigit() and int(v.strip()) >= 1
                        else "Enter a whole number ≥ 1"
                    ),
                )
                self._idp_number = int(raw.strip())
        except Exception as e:
            self._logger.exception(
                f'Exception from gather script in collect_idp_number function -  {str(e)}')

    def collect_idp_discovery(self) -> None:
        """Collect IDP discovery configuration for each configured IDP."""
        try:
            for i in range(self._idp_number):
                idp_id = "idp" if i == 0 else f"idp{i + 1}"
                self._ssl_directory_list.append(idp_id)

                _info_panel(
                    f"🔐  Identity Provider — {idp_id}",
                    f"[bold white]Configure IDP [cyan]{idp_id}[/cyan] for IBM Content Assistant.[/bold white]\n\n"
                    "[bold cyan]With Discovery URL:[/bold cyan]\n"
                    "  [dim]The operator fetches the IDP configuration automatically from the discovery endpoint.[/dim]\n"
                    "  [dim]Discovery URLs end with [bold].well-known/openid-configuration[/bold][/dim]\n\n"
                    "[bold cyan]Without Discovery URL:[/bold cyan]\n"
                    "  [dim]You will configure the IDP fields manually in the property file.[/dim]\n\n"
                    "[dim]Most modern OIDC providers (Keycloak, Azure AD, Okta) support discovery.[/dim]",
                )

                discovery_enabled = safe_questionary_prompt(
                    questionary.confirm,
                    message=f"Does {idp_id} support OIDC Discovery?",
                    default=True,
                    style=_QS,
                )

                if discovery_enabled:
                    while True:
                        print()
                        url = safe_questionary_prompt(
                            questionary.text,
                            message="Enter the OIDC Discovery URL:",
                            instruction="(must end with /.well-known/openid-configuration)",
                            style=_QS,
                            validate=lambda v: (
                                True if v.strip().endswith(".well-known/openid-configuration")
                                else "URL must end with /.well-known/openid-configuration"
                            ),
                        )

                        if self.check_discovery_url(url):
                            idp = self.Idp(discovery_enabled, idp_id, url)
                            idp.parse_discovery_url()
                            self._idp_info.append(idp)
                            break
                        else:
                            print()
                            print(Panel.fit(
                                "[bold red]✗[/bold red]  Discovery URL is invalid.\n"
                                "  Ensure the URL ends with "
                                "[bold cyan]/.well-known/openid-configuration[/bold cyan]",
                                border_style="red",
                            ))
                else:
                    idp = self.Idp(discovery_enabled, idp_id)
                    self._idp_info.append(idp)

        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in collect_idp_discovery function - {str(e)}")

    # Create a function to return all the deployment options as a dictionary
    def to_dict(self):
        # Derive the auth_type for the summary from the first configured vector DB,
        # since collect_auth_type() stores the result in the VectorDatabase instance
        # rather than writing back to self._auth_type.
        first_db = self._vector_database_details[0] if self._vector_database_details else None
        auth_type_display = first_db.get_db_auth_type if first_db is not None else self._auth_type

        return {
            "vector_database_details": self.vector_db_details,
            "cas_version": self.cas_version,
            "ccx_version": self.cas_version,   # alias used by the results display
            "platform": self.platform,
            "license_model": self.license_model,
            "ingress": self.ingress,
            "enable_admin_access": self.enable_admin_access,
            "namespace": self.namespace,
            "ai_provider_type": self.ai_provider_type,
            "create_opensearch_cluster": self.create_opensearch_cluster,
            "opensearch_storage_class": self.opensearch_storage_class,
            "opensearch_block_storage_class": self.opensearch_block_storage_class,
            "opensearch_cluster_hostname": self.opensearch_cluster_hostname,
            "opensearch_admin_password": self.opensearch_admin_password,
            "opensearch_genai_password": self.opensearch_genai_password,
            "np_support": self._np_support,
            "fips_support": self._fips_support,
            "auth_type": auth_type_display,
        }


