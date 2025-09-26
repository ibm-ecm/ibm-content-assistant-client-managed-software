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

from enum import Enum
from rich import print
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.text import Text
from urllib.parse import urlparse
from kubernetes import client, config
import requests
from ..utilities.kubernetes_utilites import KubernetesUtilities

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
        ROKS = 2
        other = 3

    def __init__(self, logger, console):

        self._idp_info = []
        self._idp_number = 0
        self._ai_provider_number = 1
        self._vector_database_number = 1
        self._vector_database_details = []
        self._platform = self.Platform(1).name
        self._license_model = "FNCM"
        self._ingress = False
        self._logger = logger
        self._console = console
        self._ssl_directory_list = []
        self._cas_version = "1.0.0"
        self._np_support = False
        self._enable_admin_access = False
        self._auth_type = self.AuthType(1).name
        self._namespace = None
        self._current_namespace = None
        self._script_type = "gather"

        config.load_kube_config()
        # Initialize Kubernetes client
        self._core_api_instance = client.CoreV1Api()
        self._k = KubernetesUtilities()

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
    def egress_support(self):
        return self._egress_support

    @property
    def np_support(self):
        return self._np_support


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

    def collect_namespace(self, namespace=None):
        # namespace parameter is none when silent mode is NOT selected, hence the conditions to skip conditions if silent mode is selected
        try:
            self._logger.info("Gathering namespace information")
            if namespace is None:
                print()
                print(Panel.fit("Namespace"))
                print()
                try:
                    current_context = config.list_kube_config_contexts()[1]

                    # Extract namespace from the current context
                    if current_context:
                        if "context" in current_context.keys():
                            if "namespace" in current_context["context"].keys():
                                self._current_namespace = current_context["context"]["namespace"]
                    else:
                        self._current_namespace = None
                except Exception as e:
                    self._current_namespace = None


            if self._platform in ["OCP", "ROKS"]:
                invalid_namespaces = ["services", "default", "calico-system", "ibm-cert-store", "ibm-observe",
                                      "ibm-system", "ibm-odf-validation-webhook"]
                invalid_namespace_to_start_with = ["openshift-", "kube-"]
            else:
                invalid_namespaces = ["services", "default", "calico-system"]
                invalid_namespace_to_start_with = ["kube-"]

            while True:
                if namespace is None:
                    answer = Prompt.ask("Enter your namespace", default=self._current_namespace)
                    if self._script_type != "deploy":
                        namespace_exists = self._k.check_namespace_exists(namespace=answer)
                        if not namespace_exists:
                            print()
                            print(Panel.fit(f"Namespace '{answer}' does not exist.\n"
                                            f"Enter a valid namespace for script to proceed.", style="bold red"))
                            print()
                            continue
                else:
                    # silent install check for namespace will not loop more than once if invalid namespace is provided
                    if self._script_type != "deploy":
                        self._logger.info(f"Checking if namespace: {namespace} exists.")
                        namespace_exists = self._k.check_namespace_exists(namespace=namespace)
                        if not namespace_exists:
                            self._logger.debug(f"Namespace '{namespace}' does not exist.")
                            print()
                            print(Panel.fit(f"Namespace '{namespace}' does not exist.\n"
                                            f"Enter a valid namespace for script to proceed.", style="bold red"))
                            print()
                            exit(1)
                    answer = namespace

                answer = answer.strip()
                # Start of namespace validation
                # Check if the answer is not empty after stripping whitespace
                if answer == '':
                    self._logger.debug(f"Namespace cannot be empty. Please try again")
                    print()
                    print("[prompt.invalid]Namespace cannot be empty. Please try again")
                    print()
                    if namespace is None:
                        continue
                    else:
                        exit(0)

                # Check if the answer is not in the list of invalid namespaces
                if any(answer in value for value in invalid_namespaces):
                    invalid_msg = ""
                    for value in invalid_namespaces:
                        invalid_msg += f"- {value}\n"
                    invalid_msg.strip()

                    print()
                    print(f"[prompt.invalid]Namespace cannot be any of the following. Please try again.\n{invalid_msg}")
                    print()
                    self._logger.debug(f"Namespace cannot be any of the following: {invalid_msg}")
                    if namespace is None:
                        continue
                    else:
                        exit(0)

                if any(answer.startswith(value) for value in invalid_namespace_to_start_with):
                    invalid_msg = ""
                    for value in invalid_namespace_to_start_with:
                        invalid_msg += f"- {value}\n"
                    invalid_msg = invalid_msg.strip()
                    print()
                    print(
                        f"[prompt.invalid]Namespace cannot start with any of the following. Please try again.\n{invalid_msg}")
                    print()
                    self._logger.debug(f"Namespace cannot start with any of the following: {invalid_msg}")
                    if namespace is None:
                        continue
                    else:
                        exit(0)

                # Check if namespace is only numbers
                if answer.isnumeric():
                    print()
                    print("[prompt.invalid]Namespace cannot be a number. Please try again.")
                    print()
                    self._logger.debug(f"Namespace cannot be a number. Please try again.")
                    if namespace is None:
                        continue
                    else:
                        exit(0)

                # Check if namespace is more than 1 word
                if " " in answer:
                    print()
                    print("[prompt.invalid]Namespace cannot contain spaces. Use '-'. Please try again.")
                    print()
                    if namespace is None:
                        continue
                    else:
                        exit(0)

                # Check if namespace has an underscore
                if "_" in answer:
                    print()
                    print("[prompt.invalid]Namespace cannot contain '_'. Use '-'. Please try again.")
                    print()
                    self._logger.debug(f"Namespace cannot be a number. Please try again.")
                    if namespace is None:
                        continue
                    else:
                        exit(0)

                # for all scripts using this function other than deploy operator we need to check if namespace exists
                self._namespace = answer
                self._logger.info(f"Namespace entered: {self._namespace}")
                break

        except Exception as e:
            self._logger.exception(
                f"Exception from gathering deployment details in collect namespace function -  {str(e)}")



    def collect_networkpolicy_info(self):
        try:

            print(Panel.fit("Generate Network Policies Templates"))
            print()
            print("Network Policies are used to control the network traffic to and from the pods in your cluster.")
            print("Network Policies are not installed automatically by the operator, but can be generated.")
            print("The operator can generate network policy templates for both egress and ingress that can be applied manually.")
            print()
            result = Confirm.ask("Do you want to generate Network Policies templates for your deployment?")
            if result:
                self._np_support = True

        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in collect version function -  {str(e)}")

    def collect_content_assistant_admin_access(self):
        try:

            print(Panel.fit("IBM Content Assistant CLI"))
            print()
            print("The IBM Content Assistant CLI provides a command line interface to manage and configure IBM Content Assistant.")
            print("By default, the CLI is not accessible. Enabling CLI Admin Access allows you to use the CLI for administrative tasks.")
            print("If enabled, the CLI can be accessed via a route on OCP/ROKS or a Ingress service on CNCF.")
            print("A private key and passphrase will be generated for secure access to the CLI.")
            print()
            result = Confirm.ask("Do you want to enable IBM Content Assistant CLI?")
            if result:
                self._enable_admin_access = True

        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in collect content assistant admin access function -  {str(e)}")


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

    # Create a function to gather vector db number from the user
    def collect_vector_db_number(self):
        try:
            print(Panel.fit("Vector Database"))

            print("IBM Content Assistant requires at least one Vector Database.")
            default = 1
            while True:
                print()
                result = IntPrompt.ask(
                    "How many Vector Database do you want to configure with IBM Content Assistant?", default=default
                )
                if result >= default:
                    self._vector_database_number = result
                    break
                print(
                    f"[prompt.invalid]Number of Vector Database to be configured must be equal or greater than [[b]{default}[/b]]")

        except Exception as e:
            self._logger.exception(
                f'Exception from gather script in collect_vector_db_number function -  {str(e)}')

    # Create a function to gather the vector DB auth type for each vector DB
    def collect_auth_type(self,db_label="VECTORDB"):
        try:

                print(Panel.fit(f"Vector Database {db_label} Authentication Type"))
                while True:
                    print()
                    print("Your Authentication Type determines the authentication mechanism used to connect to the Vector Database.")
                    print()
                    print("Select an Authentication Type")
                    print('1. Basic Authentication')
                    print('2. OpenID Connect (OIDC)')

                    result = IntPrompt.ask('Enter a valid option between [[b]1[/b] and [b]2[/b]]')

                    if 1 <= result <= 2:
                        vector_db_auth_type = self.AuthType(result).name
                        break

                    print("[prompt.invalid] Number must be between [[b]1[/b] and [b]2[/b]]")
                return vector_db_auth_type


        except Exception as e:
            # Create log for exception
            self._logger.exception(
                f"Exception from gather script in auth_type function -  {str(e)}")
            vector_db_auth_type= "BASICAUTH"
            return vector_db_auth_type

    def collect_vector_ssl_info(self):
        print()
        print("Enabling SSL ensures that the data transmitted between IBM Content Assistant and your Vector Database is encrypted and secure.\n"
              "This is especially important if your Vector Database is hosted externally or in a different network environment.\n"
              "If you selected OIDC as your authentication type, the OIDC provider connection will also be secured using SSL.")
        print()
        return Confirm.ask("Do you want to enable SSL for your database selection?")

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

    # Create a function to gather license model details
    def collect_license_model(self, version_data):
        try:
            print(Panel.fit("License and Version"))
            print()

            cas_license_url = Text("https://ibm.biz/CAS_License_1_0_0",
                                    style="link hhttps://ibm.biz/CAS_License_1_0_0")
            cas_notices_url = Text("https://ibm.biz/CAS_Notices_1_0_0",
                                   style="link https://ibm.biz/CAS_Notices_1_0_0")

            version = version_data.get("VERSION", '1.0.0' )
            self._cas_version = version

            print(Panel.fit(Text(f"Detected IBM Content Assistant Version: {version}", style="bold cyan")))
            print()

            print(Panel.fit(
                f"IMPORTANT: Review the license information for the product bundle you are deploying.\n\n"
                f"IBM Content Assistant Client Managed Software license information here: {cas_license_url}\n"
                f"IBM Software Notices here: {cas_notices_url}"))

            print()

            self._accept_license = Confirm.ask("Do you accept the International Program License?")

            if not self._accept_license:
                print("\n[prompt.invalid]You must accept the International Program License to continue.")
                exit(1)

        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in license model function -  {str(e)}")



    # Create a function to gather platform and ingress enabled from user
    def collect_platform_ingress(self):
        try:
            print(Panel.fit("Platform"))
            while True:
                print()
                print("Select a Platform Type")
                print("1. OCP")
                print("2. ROKS")
                print("3. CNCF")
                result = IntPrompt.ask('Enter a valid option [[b]1[/b] and [b]3[/b]]')

                if 1 <= result <= 3:
                    self._platform = self.Platform(result).name
                    break

                print("\n[prompt.invalid]Number must be between [[b]1[/b] and [b]3[/b]]")

            if self._platform == "other":
                print()
                self._ingress = Confirm.ask("Do you want to enable ingress creation?")


        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in collect_platform_ingress function -  {str(e)}")

    # Create a function to gather idp_number from user
    def collect_idp_number(self):
        try:
            if self._auth_type == "SCIM_IDP":
                self._idp_number = 1
                self._scim_number = 1
                self._ssl_directory_list.append("scim")
            else:
                print(Panel.fit("Identity Provider (IDP)"))
                while True:
                    print()
                    result = IntPrompt.ask(
                        "How many IDP's do you want to configure?", default=1
                    )
                    if result >= 1:
                        self._idp_number = result
                        break
                    print("[prompt.invalid]Number of IDP's must be greater than 0")
        except Exception as e:
            self._logger.exception(
                f'Exception from gather script in collect_idp_number function -  {str(e)}')

    # Create a function to gather idp_number from user
    def collect_idp_discovery(self):
        try:
            for i in range(self._idp_number):
                if i == 0:
                    idp_id = "idp"
                else:
                    idp_id = f"idp{i + 1}"

                self._ssl_directory_list.append(idp_id)

                print()
                print(Panel.fit(f"IDP ID: {idp_id}"))

                while True:
                    print()
                    print("Discovery Endpoints can used to retrieve the IDP configuration.\n"
                          "If you do not have a discovery endpoint, you can still configure the IDP manually.\n"
                          "Discovery endpoints URLs typically end with '/.well-known/openid-configuration'")
                    print()
                    discovery_enabled = Confirm.ask("Does this IDP support discovery?")

                    if discovery_enabled:
                        print()
                        url = Prompt.ask("Enter a valid URL for the IDP discovery endpoint")

                        if self.check_discovery_url(url):
                            idp = self.Idp(discovery_enabled, idp_id, url)
                            idp.parse_discovery_url()
                            self._idp_info.append(idp)
                            break
                        else:
                            print("\n[prompt.invalid]Discovery URL is invalid")
                            print(
                                '\n[prompt.invalid]Make sure your discovery URL ends with ".well-known/openid-configuration"')
                    else:
                        idp = self.Idp(discovery_enabled, idp_id)
                        self._idp_info.append(idp)
                        break



        except Exception as e:
            self._logger.exception(
                f'Exception from gather script in collect_idp function -  {str(e)}')

    # Create a function to return all the deployment options as a dictionary
    def to_dict(self):

        return {
            "vector_database_details": self.vector_db_details,
            "cas_version": self.cas_version,
            "platform": self.platform,
            "license_model": self.license_model,
            "ingress": self.ingress,
            "enable_admin_access": self.enable_admin_access,
            "namespace": self.namespace
        }


