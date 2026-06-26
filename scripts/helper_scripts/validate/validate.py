###############################################################################
#
# Licensed Materials - Property of IBM
#
# (C) Copyright IBM Corp. 2023. All Rights Reserved.
#
# US Government Users Restricted Rights - Use, duplication or
# disclosure restricted by GSA ADP Schedule Contract with IBM Corp.
#
###############################################################################

import base64
import inspect
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import time
from ipaddress import ip_address, IPv4Address, IPv6Address
from urllib.parse import urlparse

import jinja2
import requests
import typer
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from requests import Session
from requests.adapters import HTTPAdapter
from rich import print
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from ..utilities import kubernetes_utilites as k
from ..utilities.interface import idp_token_claim_results
from ..utilities.prerequisites_utilites import create_ssl_context
from ..utilities.prerequisites_utilites import collect_visible_files, \
    connect_to_server, clean_and_combine_pem_files

requests.packages.urllib3.disable_warnings()


# Function to remove protocol from URL
def remove_protocol(url):
    hostname = urlparse(url).hostname
    if hostname is None:
        hostname = url
    return hostname


class Validate:

    class CustomHTTPAdapter(HTTPAdapter):
        def __init__(self, ssl_context=None, **kwargs):
            self.ssl_context = ssl_context
            super().__init__(**kwargs)

        def init_poolmanager(self, *args, **kwargs):
            # Pass the custom SSL context to the base class's init_poolmanager
            kwargs['ssl_context'] = self.ssl_context
            super().init_poolmanager(*args, **kwargs)


    _TMP_DIR = os.path.join(os.getcwd(), "helper_scripts", "validate", "tmp")

    _CIPHERS = bytes(
        "TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-RSA-AES128-GCM-SHA256",
        'utf-8')

    # Cannot default prop to a ReadProp object because Readprop requires a logger to be passed in
    def __init__(self, logger,
                 deploy_prop=None,
                 idp_prop=None,
                 vector_db_prop=None,
                 content_assistant_prop=None,
                 pvc_size='10Mi',
                 namespace=''):

        self._namespace = namespace

        if deploy_prop:
            self._deploy_prop = deploy_prop
        else:
            self._deploy_prop = {}

        if vector_db_prop:
            self._vector_db_prop = vector_db_prop
        else:
            self._vector_db_prop = {}

        if content_assistant_prop:
            self._content_assistant_prop = content_assistant_prop
        else:
            self._content_assistant_prop = {}

        if idp_prop:
            self._idp_prop = idp_prop
        else:
            self._idp_prop = {}

        self._logger = logger
        self._kube = k.KubernetesUtilities(logger)
        self._pvc_size = pvc_size

        self.is_validated = {}

        # Collect Provider API Count
        self._provider_api_count = self._content_assistant_prop.get("_ai_providers_ids", 0)
        
        # SSL certificate folder path
        self._ssl_cert_folder = os.path.join(os.getcwd(), "propertyFile", namespace, "ssl-certs")

        # Setting for Truststore
        self.__create_tmp_folder()
        self._alias = "fncmp12Certs"
        self._dnsname = "CN=fncmp12"
        self._storetype = "PKCS12"
        self._truststore_pwd = "changeit"
        self._truststore_folder = os.path.join(self._TMP_DIR, "truststore")
        self._truststore_name = "fncm_truststore.p12"
        self._truststore_path = os.path.join(self._truststore_folder, self._truststore_name)

        self._template_folder = os.path.join(os.getcwd(), "helper_scripts", "validate", "templates")

        self.cleanup_tmp()

        # Load all jinja templates
        self._template_loader = jinja2.FileSystemLoader(self._template_folder)
        self._template_env = jinja2.Environment(loader=self._template_loader, trim_blocks=True)

    # Create getters and setters for all properties
    @property
    def db_prop(self):
        return self._db_prop

    @db_prop.setter
    def db_prop(self, db_prop):
        self._db_prop = db_prop

    @property
    def ldap_prop(self):
        return self._ldap_prop

    @ldap_prop.setter
    def ldap_prop(self, ldap_prop):
        self._ldap_prop = ldap_prop

    @property
    def deploy_prop(self):
        return self._deploy_prop

    @deploy_prop.setter
    def deploy_prop(self, deploy_prop):
        self._deploy_prop = deploy_prop

    @property
    def idp_prop(self):
        return self._idp_prop

    @idp_prop.setter
    def idp_prop(self, idp_prop):
        self._idp_prop = idp_prop

    @property
    def scim_prop(self):
        return self._scim_prop

    @scim_prop.setter
    def scim_prop(self, scim_prop):
        self._scim_prop = scim_prop

    @property
    def component_prop(self):
        return self._component_prop

    @component_prop.setter
    def component_prop(self, component_prop):
        self._component_prop = component_prop

    @property
    def user_group_prop(self):
        return self._user_group_prop

    @user_group_prop.setter
    def user_group_prop(self, user_group_prop):
        self._user_group_prop = user_group_prop

    def cleanup_tmp(self):
        if os.path.exists(self._TMP_DIR):
            shutil.rmtree(self._TMP_DIR)
            self.__recreate_folder(self._TMP_DIR)

    def __recreate_folder(self, directory):
        if os.path.exists(directory):
            shutil.rmtree(directory)
        os.mkdir(directory)
        return directory

    def parse_shell_command(self, parameter):
        # Create a function to escape any single quotes in the password
        # This is needed for the DB connection jar

        # Escape any single quotes in the password
        parameter = parameter.replace("'", "'\\''")

        return parameter



    # Returns the first file found in a directory
    # that has one of the extensions provided.
    def __get_file_from_folder(self, file_dir, extensions: list):
        files = self.__files_in_dir(file_dir, extensions)
        if len(files) == 0:
            self._logger.info(f"No files with extension:{str(extensions)} found in {file_dir}!")
            return ''
        return os.path.join(file_dir, files[0])

    # Returns a list of files that has matching extensions
    def __files_in_dir(self, dir_path, extensions: list = []):
        # list to store files
        res = []
        # Iterate directory
        files = collect_visible_files(dir_path)
        for file in files:
            # check only text files
            if len(extensions) != 0:
                if file.endswith(tuple(extensions)):
                    res.append(file)
            else:
                res.append(file)
        return res

    def __create_tmp_folder(self):
        try:
            if not os.path.exists(self._TMP_DIR):
                os.makedirs(self._TMP_DIR)
        except Exception as e:
            self._logger.exception(
                f"Exception from validate.py script in {inspect.currentframe().f_code.co_name} function -  {str(e)}")
        return self._TMP_DIR

    # Converts a .cert file to .der in x509 format
    def __crt_to_der_x509(self, input_cert_path, output_path):
        try:
            # Remove previous temp files
            if os.path.exists(output_path):
                os.remove(output_path)

            # Create LDAP .der file
            with open(input_cert_path, 'rb') as cert_file:
                cert_file = cert_file.read()
            cert_der = x509.load_pem_x509_certificate(cert_file, default_backend())
            with open(output_path, 'wb') as file:
                file.write(cert_der.public_bytes(serialization.Encoding.PEM))

        except Exception as e:
            self._logger.exception(
                f"Exception from validate.py script in {inspect.currentframe().f_code.co_name} function -  {str(e)}")

        return output_path

    # Function to validate WatsonX SaaS credentials using ibm-watsonx-ai SDK
    def validate_watsonx_saas(self, api_key, space_id, url, progress):
        """ Validate WatsonX SaaS credentials using ibm-watsonx-ai SDK """
        try:
            from ibm_watsonx_ai import Credentials, APIClient
            import warnings
            import logging as py_logging

            progress.log()
            progress.log(f"Validating WatsonX SaaS credentials")

            # Suppress warnings and logging from ibm-watsonx-ai library during validation
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                # Temporarily suppress ibm-watsonx-ai logging
                ibm_logger = py_logging.getLogger('ibm_watsonx_ai')
                original_level = ibm_logger.level
                ibm_logger.setLevel(py_logging.CRITICAL)
                
                try:
                    # Create credentials object for SaaS
                    credentials = Credentials(
                        url=url,
                        api_key=api_key
                    )

                    # Try to create an API client with the credentials and space_id
                    # This will validate both the credentials and space_id access
                    try:
                        client = APIClient(credentials, space_id=space_id)
                        
                        progress.log()
                        progress.log(f"WatsonX SaaS credentials validated successfully")
                        return True

                    except Exception as client_error:
                        progress.log()
                        progress.log(f"Failed to validate WatsonX SaaS credentials: {str(client_error)}")
                        return False
                finally:
                    # Restore original logging level
                    ibm_logger.setLevel(original_level)

        except ImportError:
            progress.log()
            progress.log(f"ibm-watsonx-ai package not installed. Please install it using: pip install ibm-watsonx-ai")
            self._logger.error("ibm-watsonx-ai package not installed")
            return False
        except Exception as e:
            progress.log()
            progress.log(f"Exception occurred while validating WatsonX SaaS: {str(e)}")
            self._logger.exception(
                f"Exception from validate.py script in {inspect.currentframe().f_code.co_name} function -  {str(e)}")
            return False

    # Function to validate WatsonX Lightweight credentials using ibm-watsonx-ai SDK
    def validate_watsonx_lightweight(self, api_key, username, url, progress, cert_path=None):
        """ Validate WatsonX Lightweight (CPD) credentials using ibm-watsonx-ai SDK """
        try:
            from ibm_watsonx_ai import Credentials, APIClient
            import warnings
            import logging as py_logging

            progress.log()
            progress.log(f"Validating WatsonX Lightweight credentials")

            # Suppress warnings and logging from ibm-watsonx-ai library during validation
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                # Temporarily suppress ibm-watsonx-ai logging
                ibm_logger = py_logging.getLogger('ibm_watsonx_ai')
                original_level = ibm_logger.level
                ibm_logger.setLevel(py_logging.CRITICAL)
                
                combined_cert_path = None
                try:
                    # Create credentials object for CPD (Lightweight)
                    credentials_params = {
                        "url": url,
                        "api_key": api_key,
                        "username": username,
                        "version": "5.3",
                        "instance_id": "openshift"
                    }
                    
                    # Add SSL certificate if provided
                    # If cert_path is a file, get its parent directory for processing
                    # If cert_path is a directory, use it directly
                    if cert_path and os.path.exists(cert_path):
                        if os.path.isfile(cert_path):
                            cert_folder = os.path.dirname(cert_path)
                        else:
                            cert_folder = cert_path
                        
                        # Use clean_and_combine_pem_files to properly handle certificate chains
                        cert_result = clean_and_combine_pem_files(
                            self._logger,
                            cert_folder,
                            self._TMP_DIR,
                            "watsonx_lightweight"
                        )
                        
                        if cert_result is not None:
                            combined_cert_path, _ = cert_result
                            if combined_cert_path and os.path.exists(combined_cert_path):
                                credentials_params["verify"] = combined_cert_path
                                progress.log()
                                progress.log(f"Using combined certificate bundle for SSL verification")
                            else:
                                progress.log()
                                progress.log(Panel.fit(
                                    Text("Warning: Could not process SSL certificate. Attempting connection without certificate verification."),
                                    style="bold yellow"))
                        else:
                            progress.log()
                            progress.log(Panel.fit(
                                Text("Warning: Could not process SSL certificate. Attempting connection without certificate verification."),
                                style="bold yellow"))
                    
                    credentials = Credentials(**credentials_params)

                    # Try to create an API client to validate credentials
                    try:
                        client = APIClient(credentials)
                        # Try to get client details to verify connection
                        client.version
                        
                        progress.log()
                        progress.log(f"WatsonX Lightweight credentials validated successfully")
                        return True

                    except Exception as client_error:
                        progress.log()
                        progress.log(f"Failed to validate WatsonX Lightweight credentials: {str(client_error)}")
                        return False
                finally:
                    # Restore original logging level
                    ibm_logger.setLevel(original_level)
                    # Clean up temporary combined certificate file
                    if combined_cert_path and os.path.exists(combined_cert_path):
                        try:
                            os.remove(combined_cert_path)
                            self._logger.debug(f"Cleaned up temporary certificate file: {combined_cert_path}")
                        except Exception as cleanup_error:
                            self._logger.debug(f"Could not clean up temporary certificate file: {cleanup_error}")

        except ImportError:
            progress.log()
            progress.log(f"ibm-watsonx-ai package not installed. Please install it using: pip install ibm-watsonx-ai")
            self._logger.error("ibm-watsonx-ai package not installed")
            return False
        except Exception as e:
            progress.log()
            progress.log(f"Exception occurred while validating WatsonX Lightweight: {str(e)}")
            self._logger.exception(
                f"Exception from validate.py script in {inspect.currentframe().f_code.co_name} function -  {str(e)}")
            return False

    # Function to verify all defined provider API credentials
    def validate_ai_provider_apis(self, task, progress):
        """ Verify Provider API credentials based on provider type """
        try:

            progress.log(Panel.fit(Text("Verifying AI Provider Credentials"), style="bold cyan"))
            progress.log()

            provider_api_passed = []

            for ai_provider in self._content_assistant_prop["_ai_providers_ids"]:
                provider_name = self._content_assistant_prop[ai_provider]["AI_PROVIDER_LABEL"]
                provider_api_key = self._content_assistant_prop[ai_provider]["API_KEY"]
                provider_url = self._content_assistant_prop[ai_provider].get("URL", "")

                progress.log()
                progress.log(f"Verifying credentials for {provider_name}...")

                # Check if this is SaaS (has SPACE_ID) or Lightweight (has USERNAME)
                if "SPACE_ID" in self._content_assistant_prop[ai_provider]:
                    # WatsonX SaaS validation
                    provider_space_id = self._content_assistant_prop[ai_provider]["SPACE_ID"]
                    
                    if not provider_api_key or not provider_space_id or not provider_url:
                        progress.log()
                        progress.log(Panel.fit(
                            Text(f"API Key, Space ID, or URL is missing for {provider_name}. Please check the configuration."),
                                 style="bold red"))
                        self._logger.info(f"API Key, Space ID, or URL is missing for {provider_name}.")
                        provider_api_passed.append(False)
                        self.is_validated[ai_provider] = False
                        progress.advance(task)
                        continue

                    # Validate using WatsonX SaaS method
                    validation_success = self.validate_watsonx_saas(provider_api_key, provider_space_id, provider_url, progress)

                elif "USERNAME" in self._content_assistant_prop[ai_provider]:
                    # WatsonX Lightweight validation
                    provider_username = self._content_assistant_prop[ai_provider]["USERNAME"]
                    
                    if not provider_api_key or not provider_username or not provider_url:
                        progress.log()
                        progress.log(Panel.fit(
                            Text(f"API Key, Username, or URL is missing for {provider_name}. Please check the configuration."),
                                 style="bold red"))
                        self._logger.info(f"API Key, Username, or URL is missing for {provider_name}.")
                        provider_api_passed.append(False)
                        self.is_validated[ai_provider] = False
                        progress.advance(task)
                        continue

                    # Check for SSL certificate if SSL is enabled
                    cert_folder = None
                    if self._content_assistant_prop[ai_provider].get("SSL_ENABLED", False):
                        # Determine the provider number for folder naming
                        provider_number = self._content_assistant_prop["_ai_providers_ids"].index(ai_provider) + 1
                        if provider_number == 1:
                            ai_provider_folder = os.path.join(self._ssl_cert_folder, "ai-provider")
                        else:
                            ai_provider_folder = os.path.join(self._ssl_cert_folder, f"ai-provider{provider_number}")
                        
                        # Check if certificate folder exists and has certificates
                        if os.path.exists(ai_provider_folder):
                            cert_file = self.__get_file_from_folder(ai_provider_folder, ['.crt', '.pem', '.cert'])
                            if cert_file:
                                # Pass the folder path instead of individual file for proper certificate chain handling
                                cert_folder = ai_provider_folder
                                cert_filename = os.path.basename(cert_file)
                                progress.log()
                                progress.log(f"Using SSL certificate folder: {os.path.basename(ai_provider_folder)}")
                            else:
                                progress.log()
                                progress.log(Panel.fit(
                                    Text(f"SSL is enabled but no certificate found for {provider_name}"),
                                         style="bold yellow"))

                    # Validate using WatsonX Lightweight method
                    validation_success = self.validate_watsonx_lightweight(provider_api_key, provider_username, provider_url, progress, cert_folder)

                else:
                    progress.log()
                    progress.log(Panel.fit(
                        Text(f"Unknown provider type for {provider_name}. Missing SPACE_ID or USERNAME."),
                             style="bold red"))
                    self._logger.info(f"Unknown provider type for {provider_name}.")
                    provider_api_passed.append(False)
                    self.is_validated[ai_provider] = False
                    progress.advance(task)
                    continue

                if not validation_success:
                    progress.log()
                    progress.log(Panel.fit(
                        Text(f"Failed to verify credentials for {provider_name}. Please check the configuration."),
                             style="bold red"))
                    self._logger.info(f"Failed to verify credentials for {provider_name}.")
                    provider_api_passed.append(False)
                    self.is_validated[ai_provider] = False
                    progress.advance(task)
                    continue

                provider_api_passed.append(True)
                self.is_validated[ai_provider] = True
                progress.log()
                progress.log(Panel.fit(Text(f"Credentials verified successfully for Provider: {provider_name}"), style="bold green"))
                progress.advance(task)


            if all(provider_api_passed):
                progress.log()
                progress.log(Panel.fit(Text("All Provider credentials verified successfully!"), style="bold green"))
                self._logger.info("All Provider credentials verified successfully!")
                return True

            else:
                progress.log()
                progress.log(Panel.fit(Text("Some Provider credentials are missing or invalid. Please check the configuration."), style="bold red"))
                self._logger.info("Some Provider credentials are missing or invalid.")
                return False

        except Exception as e:
            progress.log()
            progress.log(Panel.fit(
                Text(f"An error occurred while verifying provider credentials: {str(e)}"),
                     style="bold red"))
            self._logger.exception(
                f"Exception from validate.py script in {inspect.currentframe().f_code.co_name} function -  {str(e)}")
            return False

    # Converts .key files to .der in PKCS8 format
    def __key_to_der_PKCS8(self, input_key_path, output_path):
        try:
            # Remove previous temp files
            if os.path.exists(output_path):
                os.remove(output_path)

            # Create LDAP .der file
            with open(input_key_path, 'rb') as key_data:
                key = serialization.load_pem_private_key(
                    key_data.read(),
                    password=None,
                    backend=default_backend()
                )

            pkcs8_key = key.private_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )

            with open(output_path, "wb") as outfile:
                outfile.write(pkcs8_key)

        except Exception as e:
            self._logger.exception(
                f"Exception converting key to DER conversion -  {str(e)}")

        return output_path




    def retrieve_token(self, url, payload, progress, cert_path=False, auth=None):

        """ Retrieve token from IDP """
        try:
            response = None

            headers = {
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            # Add basic auth if only client_basic_auth is provided
            if auth:
                headers.update(auth)

            if cert_path:
                progress.log()
                progress.log("Retrieving access and id_token token over SSL...")

                context = create_ssl_context(client_cert_file=cert_path)
                client_session = Session()
                client_session.mount("https://", self.CustomHTTPAdapter(ssl_context=context))

                response = client_session.post(url, headers=headers, data=payload, timeout=5)

                # Check if "access_token" or 'id_token' is in the response
                if response.status_code == 200:
                    if 'access_token' in response.json() or 'id_token' in response.json():
                        return response.json(), True

                return response, False


            progress.log()
            progress.log("Retrieving access and id_token token...")
            response = requests.post(url, headers=headers, data=payload, verify=False, timeout=5)

            # Check if "access_token" is in the response
            if response.status_code == 200:
                if "access_token" in response.json() or 'id_token' in response.json():
                    return response.json(), True

            return response.json(), False

        # Check for SSL errors
        except requests.exceptions.SSLError as e:
            self._logger.info(f"SSL Error: {e}")
            self._logger.info("Attempting to retrieve token using non-SSL connection...")

            progress.log()
            progress.log(Text("SSL error occurred while retrieving token. Attempting connection without certificate verification.",
                              style="bold yellow"))
            response = requests.post(url, headers=headers, data=payload, verify=False, timeout=5)

            if response.status_code == 200:
                if "access_token" in response.json() or 'id_token' in response.json():
                    return response.json(), True

            return response.json(), False
        except requests.exceptions.RequestException as e:
            return response.json(), False
        except Exception as e:
            return response.json(), False


    def base64url_decode(self, input_str):

        """ Decodes Base64 URL-safe encoded string """

        rem = len(input_str) % 4
        if rem > 0:
            input_str += '=' * (4 - rem)
        return base64.urlsafe_b64decode(input_str.encode('utf-8'))

    def load_jwk_rsa_key(self, jwk):

        """ Loads a RSA public key from a JSON Web Key"""

        # RSA modulus 
        n = int.from_bytes(self.base64url_decode(jwk['n']), 'big')
        # public exponent
        e = int.from_bytes(self.base64url_decode(jwk['e']), 'big')
        # public key
        public_key = rsa.RSAPublicNumbers(e, n).public_key(default_backend())
        return public_key

    def verify_rs256_signature(self, header_b64, payload_b64, signature_b64, public_key):

        """ Verifies an RS256 signature for a given header, payload, and signature """

        signed_data = f'{header_b64}.{payload_b64}'.encode('utf-8')
        signature = self.base64url_decode(signature_b64)
        try:
            public_key.verify(
                signature,
                signed_data,
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            return True
        except Exception as e:
            self._logger.info(f"Signature verification failed: {e}")
            return False

    def decode_id_token(self, jwks_uri, id_token, client_id, cert_path=None, progress=None):

        """ Validates the id token retrieved from IDP """

        try:
            if cert_path:
                # Getting the public key with SSL verification
                progress.log()
                progress.log("Retrieving public key from JWKS Endpoint over SSL...")
                # Getting the public key
                jwks = requests.get(jwks_uri, verify=True, timeout=5).json()
            else:
                progress.log()
                progress.log("Retrieving public key from JWKS Endpoint...")
                # Getting the public key without SSL verification
                jwks = requests.get(jwks_uri, verify=False, timeout=5).json()

        except requests.exceptions.SSLError as e:
            self._logger.info(f"SSL Error: {e}")
            self._logger.info("Attempting to retrieve public key using non-SSL connection...")
            progress.log()
            progress.log(Text("SSL error occurred while retrieving public key. Attempting connection without certificate verification.",
                              style="bold yellow"))
            jwks = requests.get(jwks_uri, verify=False, timeout=5).json()
        except requests.exceptions.RequestException as e:
            error_text = jwks.text if jwks is not None and hasattr(jwks,
                                                                   "text") else "No response or response not available."
            progress.log()
            progress.log(Panel.fit(
                Text(f"Failed to retrieve public key from \"{jwks_uri}\"! Error: {str(e)}\nResponse Text: {error_text}",
                     style="bold red")))
        except Exception as e:
            progress.log()
            progress.log(Panel.fit(
                Text(f"An unexpected error occurred while retrieving public key from \"{jwks_uri}\"! Error: {str(e)}",
                     style="bold red")))
            self._logger.info(f"An unexpected error occurred: {e}")

        progress.log()
        progress.log("Parsing the token headers")
        header_b64, payload_b64, signature_b64 = id_token.split('.')
        header = json.loads(self.base64url_decode(header_b64))
        payload = json.loads(self.base64url_decode(payload_b64))

        progress.log()
        progress.log("Loading the public key")
        kid = header['kid']
        key = next(k for k in jwks['keys'] if k['kid'] == kid)
        public_key = self.load_jwk_rsa_key(key)

        if not self.verify_rs256_signature(header_b64, payload_b64, signature_b64, public_key):
            progress.log()
            progress.log(Panel.fit(Text("Invalid token signature!"), style="bold red"))
            raise ValueError("Invalid signature")

        progress.log()
        progress.log("Token signature verified successfully!")
        self._logger.info("Token signature verified successfully!")

        now = int(time.time())
        if 'exp' in payload and now > payload['exp']:
            progress.log()
            progress.log(Panel.fit(Text("Token has expired!"), style="bold red"))
            raise ValueError("Token expired")

        progress.log()
        progress.log("Token expiration time is valid!")
        self._logger.info("Token expiration time is valid!")

        return payload

    def validate_all_idps(self, task4, progress):
        idp_ids = self._idp_prop["_idp_ids"]
        validated_idps = []

        if self._scim_prop:
            progress.log()
            progress.log(
                Panel.fit(Text(f"Validating IDP for SCIM Integration"), style="bold cyan"))
            progress.log()
            progress.log(Panel.fit(Text(
                "Validation will test the IDP configuration and retrieve the access token using password flow.\n"
                "Liberty OAuth Jaas module accesses the IDP using the password grant type."), style="bold purple"))
        else:
            progress.log()
            progress.log(Panel.fit(Text("IDP Validation"), style="bold cyan"))
            progress.log()
            progress.log(Panel.fit(Text("IDP Validation is optional.\n"
                                        "During deployment, IBM Liberty will use authorization code flow to retrieve the access token.\n"
                                        "Validation will test the IDP configuration and retrieve the access token using client credentials or password flow.\n"
                                        "Any failures trying to get an access token will be ignored."),
                                   style="bold purple"))



        for idp_id in idp_ids:
            if self._scim_prop:
                validated = self.validate_idp_scim(idp_id, progress)
            else:

                validated = self.validate_idp(idp_id, progress)

            if validated:
                progress.log()
                progress.log(Panel.fit(Text(f"Successfully validated IDP: {idp_id.lower()}"), style="bold green"))

            validated_idps.append(validated)
            self.is_validated[idp_id] = validated
            progress.advance(task4)

        if all(validated_idps):
            progress.log()
            progress.log(Panel.fit(Text("All IDPs validated successfully!"), style="bold green"))
            self._logger.info("All IDPs validated successfully!")
        else:
            progress.log()
            progress.log(Panel.fit(Text("Some IDPs failed the optional validation. IBM Liberty will use the authorization code flow to retrieve the access token.\n"
                                        "Not all IDPs are required to be validated for the deployment to succeed."), style="bold purple"))
        progress.advance(task4)



    def validate_idp(self, idp_id, progress):

        """ Validates IDP """

        try:
            progress.log(Panel.fit(Text(f"Validating IDP: {idp_id.lower()}"), style="bold cyan"))

            idp_config = self._idp_prop[idp_id]
            token_endpoint = idp_config.get("TOKEN_ENDPOINT", "")
            client_id = idp_config.get("CLIENT_ID", "")
            client_secret = idp_config.get("CLIENT_SECRET", "")
            ssl_enabled = idp_config.get("IDP_SSL_ENABLED", False)
            cert_folder = os.path.join(os.getcwd(), "propertyFile", self._namespace, "ssl-certs", idp_id.lower())

            if ssl_enabled:
                # Get the certificate path
                self._logger.info(f"SSL is enabled for IDP: {idp_id.lower()}")
                progress.log()
                progress.log(Text(f"SSL is enabled for IDP: {idp_id.lower()}", style="bold cyan"))

                cert_path, san_list = clean_and_combine_pem_files(self._logger, cert_folder, self._TMP_DIR, idp_id)

                self._logger.info(f"Using certificate path: {cert_path}")

                verify_cert = cert_path
            else:
                verify_cert = False

            # Validate Server Reachability
            progress.log()
            progress.log(f"Validating server reachability for IDP: {idp_id.lower()}\n\n"
                         f"Using token endpoint for validation: {token_endpoint}")
            progress.log()

            # Get Port and Server from the token endpoint
            if not token_endpoint:
                progress.log()
                progress.log(Panel.fit(Text(f"Token endpoint is not provided for {idp_id} IDP!\n\n"
                                            f"Please check the IDP configuration in the fncm_identity_provider.toml file",
                                            style="bold red")))
                self._logger.info(f"Token endpoint is not provided for {idp_id} IDP!")
                return False

            url_parts = urlparse(token_endpoint)
            idp_url = url_parts.hostname
            idp_port = url_parts.port if url_parts.port else (443 if ssl_enabled else 80)

            if ssl_enabled:
                server_reachability = self.validate_server(progress=progress, server=idp_url, port=idp_port,
                                                           ssl_enabled=True, cert_path=cert_folder,
                                                           display_rtt=False)
            else:
                server_reachability = self.validate_server(progress=progress, server=idp_url, port=idp_port,
                                                           display_rtt=False)

            if not server_reachability and ssl_enabled:
                progress.log(
                    Text(f"Reachability over SSL failed. Attempting connection without certificate verification.",
                         style="bold yellow"), style="bold yellow")
                progress.log()

                server_reachability = self.validate_server(progress=progress, server=idp_url, port=idp_port,
                                                           display_rtt=False)

            if not server_reachability:
                return False

            # Validate the password grant type
            # Only check if the discovery URL is provided

            progress.log()
            progress.log(f"Validating client authentication methods")
            discovery_url = idp_config.get("DISCOVERY_ENDPOINT", "")
            if not discovery_url:
                progress.log()
                progress.log(Panel.fit(
                    Text(f"Discovery URL is not provided for IDP!\n"
                         f"Additional Validation will be skipped", style="bold yellow")))
                self._logger.info(f"Discovery URL is not provided for {idp_id} IDP!")
                return True

            progress.log()
            progress.log(f"Retrieving discovery document...")
            discovery = requests.get(discovery_url, timeout=5, verify=False).json()


            # Check if the discovery is valid
            if discovery is None:
                progress.log()
                progress.log(Panel.fit(Text(f"Failed to retrieve discovery document\n"
                                            f"Check the DISCOVERY_ENDPOINT in the fncm_identity_provider.toml file",
                                            style="bold red")))
                self._logger.info(f"Failed to retrieve discovery document for {idp_id} IDP!")
                return False

            # Check if "client_credentials" is in the response
            grant_types = discovery.get("grant_types_supported", [])
            if grant_types:
                if "client_credentials" not in grant_types:
                    progress.log()
                    progress.log(Panel.fit(
                        Text(f"\"client_credentials\" grant type is not supported by IDP: {idp_id.lower()}\n"
                             f"Additional validation will be skipped."),  style="bold yellow"))
                    self._logger.info(f"\"client_credentials\" grant type is not supported by IDP: {idp_id.lower()}")
                    return True
            else:
                progress.log()
                progress.log(Panel.fit(
                    Text(f"Unable to determine supported grant types from discovery document.\n"
                         f"Validation will continue to use \"client_credential\" grant"), style="bold yellow"))
                self._logger.info("Unable to determine supported grant types from discovery document.")


            self._logger.info(f"Discovery document retrieved for {idp_id} IDP: {discovery}")
            client_type = ''
            if "token_endpoint_auth_methods_supported" in discovery.keys():
                auth_methods = discovery.get("token_endpoint_auth_methods_supported", [])
                if "client_secret_post" in auth_methods:
                    client_type = 'client_secret_post'
                elif "client_secret_basic" in auth_methods:
                    client_type = 'client_secret_basic'
                else:
                    progress.log()
                    progress.log(Panel.fit(
                        Text(f"\"client_secret_post\" or \"client_secret_basic\" authentication methods are not supported by IDP: {idp_id.lower()}\n"
                             f"Additional validation will be skipped.", style="bold yellow")))
                    self._logger.info(f"\"client_secret_post\" or \"client_secret_basic\" authentication methods are not supported by IDP: {idp_id.lower()}")
                    return True
            else:
                progress.log()
                progress.log(Panel.fit(
                    Text(f"Unable to determine supported authentication methods from discovery document.\n"
                         f"Additional validation will be skipped."), style="bold yellow"))
                self._logger.info("Unable to determine supported authentication methods from discovery document.")
                return True

            progress.log()
            progress.log(Panel.fit(
                Text(f"\"{client_type}\" authentication method is supported!", style="bold green")))
            self._logger.info(f"\"{client_type}\" authentication method is supported!")

            # Retrieving token
            self._logger.info(f"Retrieving id_token from IDP using {client_type}")
            progress.log()
            progress.log("Using \"client_credentials\" grant to retrieve access token from IDP")

            # Azure Entra requires specific scope
            # Will check the Issuer Endpoint to determine if it's Azure Entra
            issuer = idp_config.get("ISSUER", "")
            if 'microsoftonline' in issuer:
                scope = f"{client_id}/.default"
            else:
                scope = "openid profile email"

            if client_type == 'client_secret_post':
                payload = {
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": scope
                }
                auth = None
            elif client_type == 'client_secret_basic':
                # For client_secret_basic, we will use the same payload but send it in the headers
                auth = {
                    'Authorization': f'Basic {base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()}'
                }
                payload = {
                    "grant_type": "client_credentials",
                    "scope": scope
                }

            response, token_retrieved = self.retrieve_token(token_endpoint, payload, progress, verify_cert, auth)

            self._logger.info(f"Response from IDP: {response}")
            self._logger.info(f"Token retrieved from IDP: {token_retrieved}")

            if not token_retrieved:
                error = response.get("error", "")
                error_description = response.get("error_description", "")

                if error == "unsupported_grant_type":
                    progress.log()
                    progress.log(Panel.fit(
                        Text(f"\"client_credentials\" grant type is not supported by IDP: {idp_id.lower()}\n"
                             f"Validation will fall back to \"password\" grant type"), style="bold yellow"))
                    self._logger.info(f"\"client_credentials\" grant type is not supported by IDP: {idp_id.lower()}")

                    # Fallback to password grant type
                    payload["grant_type"] = "password"

                    # Retrieving token
                    progress.log()
                    progress.log("Using \"password\" grant to retrieve access token from IDP")

                    response, token_retrieved = self.retrieve_token(token_endpoint, payload, progress, verify_cert,
                                                                    auth)

                    if token_retrieved:
                        progress.log()
                        progress.log(Panel.fit(
                            Text(f"Access token retrieved successfully from IDP: {idp_id.lower()}"), style="bold green"))
                        self._logger.info(f"Access token retrieved successfully from IDP: {idp_id.lower()}")
                        return True

                else:
                    progress.log()
                    progress.log(Panel.fit(
                        Text(f"Failed to retrieve token from IDP: {idp_id.lower()}"), style="bold purple"))
                    self._logger.info(f"Failed to retrieve token from IDP: {idp_id.lower()}")

                    if error or error_description:
                        progress.log()
                        progress.log(Panel.fit(Text(f"Error: {error}\nError Description: {error_description}"), style="bold purple"))
                        self._logger.info(f"Error: {error}\nError Description: {error_description}")
                    return True

            progress.log()
            progress.log(Panel.fit(
                Text(f"Access token retrieved successfully from IDP: {idp_id.lower()}"), style="bold green"))
            self._logger.info(f"Access token retrieved successfully from IDP: {idp_id.lower()}")
            return True

        except Exception as e:
            progress.log()
            progress.log(Panel.fit(Text(f"Failed to validate IDP: {idp_id}"), style="bold red"))
            self._logger.info(f"Failed to validate {idp_id} IDP! Error: {str(e)}")
            return False

    def validate_idp_scim(self, idp_id, progress):

        """ Validates IDP """
        progress.log()
        progress.log(Panel.fit(Text(f"Validating IDP for SCIM Integration: {idp_id.lower()}"), style="bold cyan"))

        try:
            idp_config = self._idp_prop[idp_id]
            token_endpoint = idp_config.get("TOKEN_ENDPOINT", "")
            client_id = idp_config.get("CLIENT_ID", "")
            client_secret = idp_config.get("CLIENT_SECRET", "")
            fncm_login_user = self._user_group_prop.get("FNCM_LOGIN_USER", "")
            fncm_login_password = self._user_group_prop.get("FNCM_LOGIN_PASSWORD", "")
            ssl_enabled = idp_config.get("IDP_SSL_ENABLED", False)
            cert_folder = os.path.join(os.getcwd(), "propertyFile", self._namespace, "ssl-certs", idp_id.lower())

            if ssl_enabled:
                # Get the certificate path
                self._logger.info(f"SSL is enabled for IDP: {idp_id.lower()}")
                progress.log()
                progress.log(Text(f"SSL is enabled for IDP: {idp_id.lower()}", style="bold cyan"))

                cert_path, san_list = clean_and_combine_pem_files(self._logger, cert_folder, self._TMP_DIR, idp_id)

                self._logger.info(f"Using certificate path: {cert_path}")

                verify_cert = True
            else:
                verify_cert = False

            # Validate Server Reachability
            progress.log()
            progress.log(f"Validating server reachability for IDP: {idp_id.lower()}\n\n"
                         f"Using token endpoint for validation: {token_endpoint}")
            progress.log()

            # Get Port and Server from the token endpoint
            if not token_endpoint:
                progress.log()
                progress.log(Panel.fit(Text(f"Token endpoint is not provided for {idp_id} IDP!\n\n"
                                            f"Please check the IDP configuration in the fncm_identity_provider.toml file",
                                            style="bold red")))
                self._logger.info(f"Token endpoint is not provided for {idp_id} IDP!")
                return False

            url_parts = urlparse(token_endpoint)
            idp_url = url_parts.hostname
            idp_port = url_parts.port if url_parts.port else (443 if ssl_enabled else 80)

            if ssl_enabled:
                server_reachability = self.validate_server(progress=progress, server=idp_url, port=idp_port,
                                                           ssl_enabled=True, cert_path=cert_folder,
                                                           display_rtt=False)
            else:
                server_reachability = self.validate_server(progress=progress, server=idp_url, port=idp_port,
                                                           display_rtt=False)

            if not server_reachability and ssl_enabled:
                progress.log(Panel.fit(
                    Text(f"Reachability over SSL failed. Attempting connection without certificate verification.",
                         style="bold yellow"), style="bold yellow"))
                progress.log()

                server_reachability = self.validate_server(progress=progress, server=idp_url, port=idp_port,
                                                           display_rtt=False)

            if not server_reachability:
                return False

            # Validate the password grant type
            # Only check if the discovery URL is provided

            progress.log()
            progress.log(f"Validating client authentication methods")
            discovery_url = idp_config.get("DISCOVERY_ENDPOINT", "")
            if not discovery_url:
                progress.log()
                progress.log(Panel.fit(
                    Text(f"Discovery URL is not provided for IDP!\n"
                         f"Additional Validation will be skipped"), style="bold yellow"))
                self._logger.info(f"Discovery URL is not provided for {idp_id} IDP!")
                return True

            progress.log()
            progress.log(f"Retrieving discovery document...")
            discovery = requests.get(discovery_url, timeout=5, verify=False).json()


            # Check if the discovery is valid
            if discovery is None:
                progress.log()
                progress.log(Panel.fit(Text(f"Failed to retrieve discovery document\n"
                                            f"Check the DISCOVERY_ENDPOINT in the fncm_identity_provider.toml file",
                                            style="bold red")))
                self._logger.info(f"Failed to retrieve discovery document for {idp_id} IDP!")
                return False

            # Check if "client_credentials" is in the response
            grant_types = discovery.get("grant_types_supported", [])
            if grant_types:
                if "client_credentials" not in grant_types:
                    progress.log()
                    progress.log(Panel.fit(
                        Text(f"\"client_credentials\" grant type is not supported by IDP: {idp_id.lower()}\n"
                             f"Additional validation will be skipped."),  style="bold yellow"))
                    self._logger.info(f"\"client_credentials\" grant type is not supported by IDP: {idp_id.lower()}")
                    return True
            else:
                progress.log()
                progress.log(Panel.fit(
                    Text(f"Unable to determine supported grant types from discovery document.\n"
                         f"Validation will continue to use \"client_credential\" grant"), style="bold yellow"))
                self._logger.info("Unable to determine supported grant types from discovery document.")


            self._logger.info(f"Discovery document retrieved for {idp_id} IDP: {discovery}")
            client_type = ''
            if "token_endpoint_auth_methods_supported" in discovery.keys():
                auth_methods = discovery.get("token_endpoint_auth_methods_supported", [])
                if "client_secret_post" in auth_methods:
                    client_type = 'client_secret_post'
                elif "client_secret_basic" in auth_methods:
                    client_type = 'client_secret_basic'
                else:
                    progress.log()
                    progress.log(Panel.fit(
                        Text(f"\"client_secret_post\" or \"client_secret_basic\" authentication methods are not supported by IDP: {idp_id.lower()}\n"
                             f"Additional validation will be skipped."), style="bold yellow"))
                    self._logger.info(f"\"client_secret_post\" or \"client_secret_basic\" authentication methods are not supported by IDP: {idp_id.lower()}")
                    return True
            else:
                progress.log()
                progress.log(Panel.fit(
                    Text(f"Unable to determine supported authentication methods from discovery document.\n"
                         f"Additional validation will be skipped."), style="bold yellow"))
                self._logger.info("Unable to determine supported authentication methods from discovery document.")
                return True

            progress.log()
            progress.log(Panel.fit(
                Text(f"\"{client_type}\" authentication method is supported!"), style="bold green"))
            self._logger.info(f"\"{client_type}\" authentication method is supported!")

            # Retrieving token
            self._logger.info(f"Retrieving token from IDP using password grant type")
            progress.log()
            progress.log("Using password grant to retrieve access token from IDP")

            # Azure Entra requires specific scope
            # Will check the Issuer Endpoint to determine if it's Azure Entra
            issuer = idp_config.get("ISSUER", "")
            if 'microsoftonline' in issuer:
                scope = f"api://{client_id}/.default"
            else:
                scope = "openid profile email"

            if client_type == 'client_secret_post':
                payload = {
                    "grant_type": "password",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "username": fncm_login_user,
                    "password": fncm_login_password,
                    "scope": scope
                }
                auth = None
            elif client_type == 'client_secret_basic':
                # For client_secret_basic, we will use the same payload but send it in the headers
                auth = {
                    'Authorization': f'Basic {base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()}'
                }
                payload = {
                    "grant_type": "password",
                    "scope": scope,
                    "username": fncm_login_user,
                    "password": fncm_login_password,
                }

            response, token_retrieved = self.retrieve_token(token_endpoint, payload, progress, verify_cert, auth)

            self._logger.info(f"Response from IDP: {response}")
            self._logger.info(f"Token retrieved from IDP: {token_retrieved}")

            if not token_retrieved:
                error = response.get("error", "")
                error_description = response.get("error_description", "")

                progress.log()
                progress.log(Panel.fit(
                    Text(f"Failed to retrieve token from IDP: {idp_id.lower()}"), style="bold red"))
                self._logger.info(f"Failed to retrieve token from IDP: {idp_id.lower()}")

                if error or error_description:
                    progress.log()
                    progress.log(
                        Panel.fit(Text(f"Error: {error}\nError Description: {error_description}"),
                                  style="bold red"))
                    self._logger.info(f"Error: {error}\nError Description: {error_description}")
                return False

            if token_retrieved:
                if token_retrieved:
                    progress.log()
                    progress.log(Panel.fit(
                        Text(f"Token retrieved successfully from IDP: {idp_id.lower()}"), style="bold green"))
                    self._logger.info(f"Token retrieved successfully from IDP: {idp_id.lower()}")

                id_token = response.get("id_token", "")

                if not id_token:
                    progress.log()
                    progress.log(Panel.fit(
                        Text(f"ID Token is not present in the response from IDP: {idp_id.lower()}\n"
                             f"Please check the IDP configuration and ensure that the ID Token is being returned.",
                             style="bold red")))
                    self._logger.info(f"ID Token is not present in the response from IDP: {idp_id.lower()}")
                    return False

                progress.log()
                progress.log("Using JWKS URI to decode the IDP ID token")

                jwks_uri = idp_config.get("JWKS_ENDPOINT", "")
                if not jwks_uri:
                    progress.log()
                    progress.log(Panel.fit(Text(f"JWKS URI is not provided for {idp_id} IDP!\n"
                                                f"Add the JWKS_ENDPOINT in the fncm_identity_provider.toml file"
                                                f"This is needed to be able to decode the IDP token",
                                                style="bold red")))
                    self._logger.info(f"JWKS_ENDPOINT is not provided for {idp_id} IDP!")
                    return False

                # Validate token
                decoded_output = self.decode_id_token(jwks_uri, id_token, client_id, verify_cert, progress)

                if decoded_output:
                    self._logger.info(f"Decoded output : {decoded_output}")
                    found_claims = {}
                    missing_claims = []

                    # Create a list of tuples
                    # with expected token claims from the IDP configuration

                    # Create a dictionary with expected token claims from the IDP configuration
                    claim_dict = {"USER_IDENTIFIER": idp_config.get("USER_IDENTIFIER", ""),
                                  "UNIQUE_USER_IDENTIFIER": idp_config.get("UNIQUE_USER_IDENTIFIER", ""),
                                  "USER_IDENTIFIER_TO_CREATE_SUBJECT": idp_config.get(
                                      "USER_IDENTIFIER_TO_CREATE_SUBJECT", "")}

                    self._logger.info(f"Expected claims from IDP: {claim_dict}")

                    for key, value in claim_dict.items():
                        if value in decoded_output:
                            found_claims[key] = (value, decoded_output[value])
                            self._logger.info(f"{key} is present in the decoded output.")
                        else:
                            missing_claims.append(value)
                            self._logger.info(f"{value} is NOT present in the decoded output.")

                    results = idp_token_claim_results(found_claims, missing_claims)

                    progress.log()
                    progress.log(results)

                    if missing_claims:
                        self._logger.info(f"Missing claims in the decoded output: {', '.join(missing_claims)}")
                        self._logger.info(f"Failed to validate token claims from IDP: {idp_id.lower()}!")

                        idp_token_claim_response = Text(
                            f"Failed to validate token claims from IDP: {idp_id.lower()}\n"
                            f"Missing claims in the decoded output: {', '.join(missing_claims)}"
                            f"Review the access token and claim parameters in the fncm_identity_provider.toml file\n"
                            f"Please check the IDP configuration and ensure that the required claims are present.",
                            style="bold red")

                        progress.log()
                        progress.log(Panel.fit(idp_token_claim_response, style="bold red"))
                        return False

                    self._logger.info(f"Successfully validated all token claims from IDP: {idp_id.lower()}!")
                    idp_token_claim_response = Text(
                        f"Successfully validated all token claims from IDP: {idp_id.lower()}")
                    progress.log()
                    progress.log(Panel.fit(idp_token_claim_response, style="bold green"))

                    return True
                else:
                    progress.log()
                    progress.log(Panel.fit(Text(f"Failed to decode IDP ID token: {idp_id.lower()}"), style="bold red"))
                    self._logger.info(f"Failed to decode IDP ID token: {idp_id.lower()}")
                    return False
            else:
                progress.log()
                progress.log(Panel.fit(
                    Text(f"Failed to retrieve token from ID IDP: {idp_id.lower()}"), style="bold red"))
                self._logger.info(f"Failed to retrieve token from IDP: {idp_id.lower()}")
                return False

        except Exception as e:
            progress.log()
            progress.log(Panel.fit(Text(f"Failed to validate IDP: {idp_id}"), style="bold red"))
            self._logger.info(f"Failed to validate {idp_id} IDP! Error: {str(e)}")
            return False

    def encode_base64(self, data):
        """
        Method name: encode_base64
        Author: Anisha Suresh (anisha-suresh@ibm.com)
        Description: Encodes a string into its base64 format.
        Parameters:
            data (str) : The string to be encoded.
        Returns:
            encoded_data (str): The encoded string.
        Raises:
            Exception: If an error occurs while encoding the string.
        """
        try:
            self._logger.info(f"Encoding data : {data}.")
            encoded_data = base64.b64encode(data.encode()).decode()
            self._logger.info(f"Encoded data : {encoded_data}.")
            return encoded_data
        except Exception as e:
            self._logger.error(f"An error occurred during encoded the data : {e}")

    def run_command(self, command):
        """
        Method name: run_command
        Author: Anisha Suresh (anisha-suresh@ibm.com)
        Description:  Executes shell commands
        Parameters:
            command (str): The command to the to be executed.
        Returns:
            str: The standard output (stdout) if the command runs successfully.
                The standard error (stderr) if an error occurs.
        Raises:
            Exception: If an error occurs while executing the command.
        """
        try:
            self._logger.info(f"Executing command : {command}")
            result = subprocess.run(shlex.split(command), capture_output=True, text=True)
            if result.returncode != 0:
                self._logger.error(
                    f"\nAn error occurred during execution of the command -- stdout : {result.stdout}, stderror : {result.stderr}")
                return result.stderr
            self._logger.info(f"Output of execution : {result.stdout}")
            return result.stdout
        except Exception as e:
            self._logger.error(f"An exception occurred during running the command -- {command} : {e}")
            return str(e)

    def remove_file(self, file_path):
        """
        Method name: remove_file
        Author: Anisha Suresh (anisha-suresh@ibm.com)
        Description:  Removes the file at the given file path.
        Parameters:
            file_path (str): The path to the file to be removed.
        Returns: None
        Raises:
            Exception: If an error occurs while removing the file.
        """
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                self._logger.info(f"Removed the file : {file_path}")
        except Exception as e:
            self._logger.error(f"An exception occurred during removal of file : {file_path}. Error : {e}")



    # Output cipher for the supplied connection
    @staticmethod
    def output_cipher(cipher, protocol, progress):
        message = Text(f"SSL protocol used: \"{protocol}\", is supported!", style="bold green")
        progress.log()
        progress.log(message)

        message = Text(f"SSL cipher used: \"{cipher[0]}\", is accepted!", style="bold green")
        progress.log()
        progress.log(message)

    # Output latency for the supplied connection
    @staticmethod
    def output_latency(rtt, progress, type="LDAP"):

        if type == "LDAP":
            max_time = 300
            min_time = 100
        else:
            max_time = 30
            min_time = 10

        if rtt < min_time:
            message = f"Acceptable Latency Range: 0ms - {min_time}ms"
            style = "bold green"
        elif min_time < rtt < max_time:
            message = f"Performance Degradation Latency Range: {min_time}ms - {max_time}ms"
            style = "bold yellow"
        else:
            message = f"Potential Failure Latency Range: > {max_time}ms"
            style = "bold red"

        progress.log()
        progress.log(Panel.fit(Text("Detected Connection Latency: {:.2f}ms \n"
                          "{}".format(rtt, message), style=style), style=style))
        progress.log()

    # Use JAR to test DB connection
    def __check_connection_with_jar(self, jar_cmd, progress):
        try:
            if platform.system() == 'Windows':
                output = subprocess.check_output(["powershell.exe", jar_cmd], shell=True, stderr=subprocess.PIPE,
                                                 universal_newlines=True)
            else:
                output = subprocess.check_output(jar_cmd, shell=True, stderr=subprocess.PIPE, universal_newlines=True)
            self._logger.info(output)
            if "failure" in output.lower():
                raise subprocess.CalledProcessError(1, jar_cmd, stderr=output)
            round_trip_statement = output.split("Round Trip time:")[1]
            match = re.search(r'([\d.]+)', round_trip_statement)
            if match:
                self.roundtriptime = float(match.group(1))

            return True
        except subprocess.CalledProcessError as error:
            self._logger.info(error.stderr)
            progress.log()
            progress.log(Text(error.stderr, style="bold red"))

            if "PKIX path building failed" in error.stderr or "Connection failure with : TLSv1.3" in error.stderr:
                progress.log()
                progress.log(Text(
                    f"SSL Certificate could not be validated, please check the supplied certificate in propertyFile/{self._namespace}/ssl-certs.",
                    style="bold red"))

            return False

    def get_unique_storageclass(self) -> set:
        sc_set = {self._deploy_prop["SLOW_FILE_STORAGE_CLASSNAME"]}
        return sc_set

    def validate_all_storage_classes(self, task1, progress):
        # Uses a set to skip checked the same storage class twice
        sc_set = self.get_unique_storageclass()

        for storage_class in sc_set:
            progress.log(Panel.fit(Text(f"Validating storage class: {storage_class}"), style="bold cyan"))
            self.validate_sample_sc(storage_class, "ReadWriteMany", "cas-test-pvc", task1, progress)

    def __check_pvc_liveliness(self, sample_pvc_name, task1, progress):
        # 30 attempts, 10 seconds each; total ~300 seconds / 5 mins
        TIMEOUT_ATTEMPTS = 30
        SLEEP_TIMER = 10

        for i in range(TIMEOUT_ATTEMPTS):
            progress.log(f"\nChecking for {sample_pvc_name} liveness - Attempt {i + 1}/{TIMEOUT_ATTEMPTS}\n")
            validated = True
            try:
                validated = self._kube.check_pvc_bound(namespace=self._namespace, pvc_name=sample_pvc_name)
                if not validated:
                    progress.log(Text(f"\n\"{sample_pvc_name}\" not yet found, waiting {SLEEP_TIMER} seconds to retry",
                                      style="bold yellow"))
                    progress.log()
                    time.sleep(SLEEP_TIMER)
                else:
                    progress.log(
                        Panel.fit(Text(f"\"{sample_pvc_name}\" is found in Bound state!"), style="bold green"))
                    progress.log()
                    progress.advance(task1)
                    return True
            except Exception as e:
                # If cannot find pvc in bound PVC grep, validation is not complete
                # and will keep waiting
                self._logger.exception(e)
                progress.log(f"Error occurred while when checking \"{sample_pvc_name}\" liveness")
                progress.log()
                progress.log(Syntax(str(e.stderr), "bash", theme="ansi_dark"))
                return False


        # Passed 60 seconds and all attempts, still cannot find PVC
        self._logger.info(f"Failed to allocate the persistent volumes using PVC: \"{sample_pvc_name}\"!")
        progress.log()
        progress.log(Panel.fit(Text(f"Failed to allocate PVC: \"{sample_pvc_name}\"!"), style="bold red"))
        progress.advance(task1)
        return False

    # Creates a storage class yaml to apply
    def validate_sample_sc(self, sc_name, sc_mode, sample_pvc_name, task1, progress):
        # check if storage class is present
        validated = True
        try:
            if self._kube.in_cluster:
                self._logger.info("Running inside cluster, skipping storage class validation")
                progress.log()
                progress.log(Panel.fit(Text(f"Skipping storage class: \"{sc_name}\" validation, running inside cluster", style="bold yellow")))
                self.is_validated[sc_name] = True

            storage_classes = self._kube.list_storage_classes()

            if sc_name in storage_classes:
                validated = True
            else:
                validated = False

            if validated:
                progress.log()
                progress.log(Panel.fit(Text(f"Found storage class: \"{sc_name}\""), style="bold green"))
            if not validated:
                self._logger.info(f"Failed to find storage class: \"{sc_name}\"!\n")
                progress.log()
                progress.log(Panel.fit(Text(f"Storage class: \"{sc_name}\" not found!"), style="bold red"))
                self.is_validated[sc_name] = False
                progress.advance(task1)
                return self.is_validated[sc_name]

        except Exception as e:
            self._logger.info(e)
            progress.log()
            progress.log(Panel.fit(Text(f"Storage classes cannot be retrieved, this is usually caused by cluster permission issues\n"
                         f"Test PVC will still be created, without storage class check!"), style="bold yellow"))
            validated = False

        # remove the existing temp file if previously not removed
        pvc_filename = f"{sc_name}.yaml"
        sample_yaml_path = os.path.join(self._TMP_DIR, pvc_filename)

        data = {
            "sc_name": sc_name,
            "size": self._pvc_size,
            "sc_mode": sc_mode
        }

        rendered_pvc = self.render_pvc_template(data, sample_pvc_name)

        # write the secret data into a yaml
        with open(sample_yaml_path, 'w+') as file:
            file.write(rendered_pvc)
            self._logger.info(f"Created PVC yaml file: {pvc_filename}")

        self._kube.apply_cluster_resource_files(resource_type='pvc', resource_file=sample_yaml_path, namespace=self._namespace)

        progress.log()
        progress.log(f"Sample PVC created with storage class: {sc_name}")
        self.is_validated[sc_name] = self.__check_pvc_liveliness(sample_pvc_name, task1, progress)

        self._kube.delete_pvc(self._namespace, sample_pvc_name)

        return self.is_validated[sc_name]

    def render_pvc_template(self, values, pvc_name):
        # Get the template from the environment
        template = self._template_env.get_template('pvc.j2')

        # Render the template with the provided values
        rendered_pvc = template.render(
            values=values,
            sample_pvc_name=pvc_name
        )

        return rendered_pvc

    # Looks for yaml files in the folder path and applies it with kubectl, will not look int subfolders.
    def auto_apply_all_secrets_in_folder(self, folder_path):
        yaml_ext = [".yaml", ".yml"]
        files = self.__files_in_dir(folder_path, yaml_ext)
        if len(files) == 0:
            self._logger.info(f"No files with extension:{str(yaml_ext)} found in {folder_path}!")

        for f in files:
            # Get name from secret yaml
            self._logger.info(f"Applying secret from file: {f}")
            applied = self._kube.apply_cluster_resource_files("secret", os.path.join(folder_path, f), namespace=self._namespace)
            if applied:
                print(Panel.fit(Text(f"Secret Applied: {f}", style="bold cyan")))
            else:
                print(Panel.fit(Text(f"Failed to apply secret: {f}", style="bold red")))

    def auto_apply_secrets_ssl(self):
        generated_folder = os.path.join(os.getcwd(), "generatedFiles", self._namespace)
        self.auto_apply_all_secrets_in_folder(folder_path=os.path.join(generated_folder, "secrets"))
        # only if ssl secrets folder is present will they be applied
        # Build path where secrets are generated
        secret_directories = [os.path.join(generated_folder,  "ssl"),
                              os.path.join(generated_folder,  "ssl", "trusted-certs")]

        for folder_path in secret_directories:
            if os.path.exists(folder_path):
                self.auto_apply_all_secrets_in_folder(folder_path=folder_path)

    def auto_apply_cr(self):
        generated_folder = os.path.join(os.getcwd(), "generatedFiles", self._namespace)
        applied = self._kube.apply_cluster_resource_files("custom resource", os.path.join(generated_folder, "ibm_content_assistant_cr.yaml"), namespace=self._namespace)
        if applied:
            print(Panel.fit(Text(f"Custom Resource Applied: ibm_content_assistant_cr.yaml", style="bold cyan")))
            return True

        print(Panel.fit(Text(f"Failed to apply custom resource: ibm_content_assistant_cr.yaml", style="bold red")))
        return False


    # Function that does the validation of the vector database URL reachability over Basic AUTH
    def validate_vector_database_over_basic_auth(self,url, username, password, progress, ssl_enabled=False, cert_path=None):

        try:
            plain_text_username= username
            plain_text_password = password
            if ssl_enabled:
                context = create_ssl_context(client_cert_file=cert_path)
                client_session = Session()
                client_session.mount("https://", self.CustomHTTPAdapter(ssl_context=context))
                response = client_session.get(url, auth=(plain_text_username, plain_text_password), timeout=10)
            else:
                response = requests.get(url, auth=(plain_text_username, plain_text_password), verify=False, timeout=10)


            if str(response.status_code).startswith("2"):
                progress.log(Panel.fit(
                    Text(f'Successfully validated the Vector Database using BasicAuth authentication'),
                         style="bold green"))
                progress.log()

                self._logger.info(
                    f'Successfully able to validate the Vector Database using BasicAuth authentication')
                return True
            else:
                progress.log(Panel.fit(
                    Text(f'Failed to validate the Vector Database URL using BasicAuth authentication\n'
                         f'HTTP return code was {response.status_code}.'),
                         style="bold red"))
                progress.log()

                self._logger.info(
                    f'Failed to validate the Vector Database URL using BasicAuth authentication. HTTP return code was {response.status_code}.')
                return False
        # Catch SSL errors separately to provide more specific logging
        except requests.exceptions.SSLError as ssl_err:
            self._logger.info(f"SSL error occurred during BasicAuth validation: {ssl_err}")
            progress.log(Panel.fit(Text(
                f"SSL Certificate could not be validated. Possibly a self-signed certificate or unrecognized CA certificate.\n"
                f"Please check the supplied certificate in propertyFile/{self._namespace}/ssl-certs."),
                style="bold yellow"))
            progress.log()

            progress.log("Attempting connection without certificate verification to validate the Vector Database using BasicAuth authentication")
            progress.log()

            response = requests.get(url, auth=(plain_text_username, plain_text_password), verify=False, timeout=10)

            if str(response.status_code).startswith("2"):
                progress.log(Panel.fit(
                    Text(f'Successfully validated the Vector Database using BasicAuth authentication'),
                         style="bold green"))
                progress.log()

                self._logger.info(
                    f'Successfully able to validate the Vector Database using BasicAuth authentication')
                return True
            else:
                progress.log(Panel.fit(
                    Text(f'Failed to validate the Vector Database URL using BasicAuth authentication\n'
                         f'HTTP return code was {response.status_code}.'),
                         style="bold red"))
                progress.log()

                self._logger.info(
                    f'Failed to validate the Vector Database URL using BasicAuth authentication. HTTP return code was {response.status_code}.')
                return False

            return False
        except Exception as e:
            self._logger.info(f"Exception occurred during BasicAuth validation: {e}")
            return False

    # Function that does the validation of the vector database URL reachability over OIDC authentication
    def validate_vector_database_over_oidc(self,token_url, client_id, client_secret, database_url, progress, ssl_enabled=False,oidc_cert=None, cert_path=None):

        if client_secret.startswith("{Base64}"):
            encoded = client_secret.replace("{Base64}", "", 1)
            plain_text_client_secret = base64.b64decode(encoded).decode("utf-8")
        else:
            plain_text_client_secret = client_secret

        try:
            if ssl_enabled:
                progress.log(Text(
                    "Retrieving bearer access token from the OIDC token endpoint using client credentials grant type over SSL"))
                progress.log()

                context = create_ssl_context(client_cert_file=oidc_cert)
                client_session = Session()
                client_session.mount("https://", self.CustomHTTPAdapter(ssl_context=context))

                token_response = client_session.post(
                    token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": client_id,
                        "client_secret": plain_text_client_secret
                    },
                    timeout=10
                )

            else:
                progress.log(Text("Retrieving bearer access token from the OIDC token endpoint using client credentials grant type"))
                progress.log()

                token_response = requests.post(
                    token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": client_id,
                        "client_secret": plain_text_client_secret
                    },
                    verify=False,
                    timeout=10
                )

        # Catch SSL errors separately to provide more specific logging
        # Catch self-signed certificate errors
        except requests.exceptions.SSLError as ssl_err:

            self._logger.info(f"SSL error occurred during OIDC validation: {ssl_err}")
            progress.log(Panel.fit(Text(
                f"SSL Certificate could not be validated. Possibly a self-signed certificate or unrecognized CA certificate.\n"
                f"Please check the supplied certificate in propertyFile/{self._namespace}/ssl-certs."),
                style="bold yellow"))
            progress.log()

            progress.log("Attempting connection without certificate verification to retrieve bearer access token from the OIDC token endpoint")
            progress.log()

            token_response = requests.post(
                token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": plain_text_client_secret
                },
                verify=False,
                timeout=10
            )

        except Exception as e:
            self._logger.info(f"Exception occurred during OIDC validation: {e}")
            return False

        self._logger.info(f"Response from OIDC token endpoint: {token_response.status_code} - {token_response.text}")
        token_json = token_response.json()
        access_token = token_json.get("access_token")

        if not access_token:
            progress.log(Panel.fit(
                Text(f"Failed to retrieve the bearer access token from the OIDC token endpoint: {token_url}\n"
                     f"\nPlease check the OIDC configuration in the cas_vector_database.toml file.",
                     ), style="bold red"))
            progress.log()

            self._logger.info(
                "Failed to retrieve the bearer access token to validate the vector database URL. The rest of the vector database validation will be skipped.")
            self._logger.info(f"Response from OIDC token endpoint: {token_json}")
            return False

        try:
            # Test a GET request with the token
            if ssl_enabled:
                progress.log(Text(f"Validating the Vector Database using OIDC based authentication over SSL"))
                progress.log()

                context = create_ssl_context(client_cert_file=cert_path)
                client_session = Session()
                client_session.mount("https://", self.CustomHTTPAdapter(ssl_context=context))

                status_response = client_session.get(
                    database_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=10
                )
            else:
                progress.log(Text(f"Validating the Vector Database using OIDC based authentication"))
                progress.log()

                status_response = requests.get(
                    database_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    verify=False,
                    timeout=10
                )

            self._logger.info(f"Response from Vector Database: {status_response.status_code} - {status_response.text}")

            if status_response.status_code == 200:
                progress.log(Panel.fit(
                    Text(f"Successfully validated the Vector Database using OIDC based authentication",
                         style="bold green")))
                progress.log()
                self._logger.info(
                    f"Successfully able to validate the Vector Database using OIDC based authentication")
                return True
            else:
                progress.log(Panel.fit(
                    Text(f"Failed to validate the Vector Database using OIDC based authentication\n"
                         f"HTTP return code was {status_response.status_code}.",
                         style="bold red")))
                progress.log()
                self._logger.info(
                    f"Failed to validate the Vector Database using OIDC based authentication. HTTP return code was {status_response.status_code}.")
                self._logger.info(f"Response from Vector Database: {status_response.text}")
                return False

        # Catch SSL errors separately to provide more specific logging
        except requests.exceptions.SSLError as ssl_err:
            self._logger.info(f"SSL error occurred during OIDC validation: {ssl_err}")
            progress.log(Panel.fit(Text(
                f"SSL Certificate could not be validated. Possibly a self-signed certificate or unrecognized CA certificate.\n"
                f"Please check the supplied certificate in propertyFile/{self._namespace}/ssl-certs."),
                style="bold yellow"))
            progress.log()

            progress.log("Attempting connection without certificate verification to validate the Vector Database using OIDC based authentication")
            progress.log()

            status_response = requests.get(
                database_url,
                headers={"Authorization": f"Bearer {access_token}"},
                verify=False,
                timeout=10
            )
            self._logger.info(f"Response from Vector Database: {status_response.status_code} - {status_response.text}")

            if status_response.status_code == 200:
                progress.log(Panel.fit(
                    Text(f"Successfully validated the Vector Database using OIDC based authentication",
                         style="bold green")))
                progress.log()
                self._logger.info(
                    f"Successfully able to validate the Vector Database using OIDC based authentication")
                return True
            else:
                progress.log(Panel.fit(
                    Text(f"Failed to validate the Vector Database using OIDC based authentication\n"
                         f"HTTP return code was {status_response.status_code}.",
                         style="bold red")))
                progress.log()
                self._logger.info(
                    f"Failed to validate the Vector Database using OIDC based authentication. HTTP return code was {status_response.status_code}.")
                self._logger.info(f"Response from Vector Database: {status_response.text}")
                return False
        except Exception as e:
            self._logger.info(f"Exception occurred during OIDC validation: {e}")
            return False

    def validate_server_name(self, server_name, progress):
        """
        Method_name: validate_server_name
        Description: Validates the server name and returns a boolean indicating whether it is valid.

        Parameters:
            server_name (str): The server name to validate.
            progress (Any): An object that provides a logging method for progress updates.

        Returns:
            bool: True if the server name is valid, False otherwise.
        """
        hostname_pattern = re.compile(
            r"^(?=.{1,253}$)(?!-)[A-Z\d-]{1,63}(?<!-)(\.(?!-)[A-Z\d-]{1,63}(?<!-))*\.?$",
            re.IGNORECASE
        )
        if server_name.startswith("[") and server_name.endswith("]"):
            stripped_server_name = server_name[1:-1]
            try:
                parsed_ip = ip_address(stripped_server_name)
                if isinstance(parsed_ip, IPv6Address):
                    return True
                elif isinstance(parsed_ip, IPv4Address):
                    message = Text(
                        "IPv4 addresses must not be enclosed in brackets."
                        "\nPlease update SERVERNAME in the property files and try again.",
                        style="bold red"
                    )
                    progress.log(message)
                    progress.log()
                    return False
            except ValueError:
                message = Text(
                    "Invalid IPv6 address format inside brackets."
                    "\nPlease update SERVERNAME in the property files and try again.",
                    style="bold red"
                )
                progress.log(message)
                progress.log()
                return False
        try:
            parsed_ip = ip_address(server_name)
            if isinstance(parsed_ip, IPv4Address):
                return True
            else:
                message = Text(
                    "IPv6 addresses must be enclosed in brackets [...]"
                    "\nPlease update SERVERNAME in the property files and try again.",
                    style="bold red"
                )
                progress.log(message)
                progress.log()
                return False
        except ValueError:
            if re.fullmatch(r"[0-9.:]+", server_name):
                message = Text(
                    "IPv4 addresses must be in valid format."
                    "\nPlease update SERVERNAME in the property files and try again.",
                    style="bold red"
                )
                progress.log(message)
                progress.log()
                return False
            if hostname_pattern.fullmatch(server_name):
                return True
            else:
                message = Text(
                    "The hostname contains invalid characters or format."
                    "\nPlease update SERVERNAME in the property files and try again.",
                    style="bold red"
                )
                progress.log(message)
                progress.log()
                return False

    # Main function that does the vector database endpoint validation
    def validate_vector_database_endpoint(self, db_id, auth_type, task, progress, cert=None, oidc_cert=None):

        validated = True
        progress.log(Panel.fit(Text(f"Validating Authentication Vector Database: {db_id}"), style="bold cyan"))
        progress.log()

        url = self._vector_db_prop[db_id]["DATABASE_URL"]
        ssl_enabled = self._vector_db_prop[db_id]['DATABASE_SSL_ENABLED']

        if auth_type.lower() == "basicauth":
            progress.log(Text(f"Validating using Basic Authentication"))
            progress.log()

            validated = self.validate_vector_database_over_basic_auth(
                url,
                self._vector_db_prop[db_id]["DATABASE_USERNAME"],
                self._vector_db_prop[db_id]["DATABASE_USER_PASSWORD"],
                progress,
                ssl_enabled=ssl_enabled,
                cert_path=cert
            )
        else:
            progress.log(Text(f"Validating using OIDC Authentication"))
            progress.log()

            validated = self.validate_vector_database_over_oidc(
                token_url=self._vector_db_prop[db_id]["DATABASE_OIDC_ENDPOINT"],
                client_id=self._vector_db_prop[db_id]["DATABASE_OIDC_CLIENT_ID"],
                client_secret=self._vector_db_prop[db_id]["DATABASE_OIDC_CLIENT_SECRET"],
                database_url=url,
                progress=progress,
                ssl_enabled=ssl_enabled,
                cert_path=cert,
                oidc_cert=oidc_cert
            )

        return validated


    # Validates a single LDAP, defaults to the first one by its id: "LDAP"
    def validate_server(self, progress, server, port, ssl_enabled=False, cert_path="", display_rtt=True, pg=False):
        connected = False

        # Test for SSL connections
        # Return a connection object, RTT and a boolean indicating if the connection was successful
        if ssl_enabled:
            progress.log(Text(f"Validating Server \"{server}\" Reachability over SSL"))
            progress.log()
            self._logger.info(f"Validating SSL connection to {server}:{port} with certificate {cert_path}")
            conn_result, rtt, connected = connect_to_server(host=server, port=int(port), ssl=True,
                                                            client_cert_file=cert_path, pg=pg, progress=progress, logger=self._logger)
        else:
            progress.log(Text(f"Validating Server \"{server}\" Reachability"))
            progress.log()
            conn_result, rtt, connected = connect_to_server(host=server, port=int(port), progress=progress, logger=self._logger)

        # Construct the message to be displayed
        # If the SSL connection was successful, display the cipher
        # If connection is successful display the RTT
        # RTT display can be disabled by setting display_rtt to False (RTT for Database is calculated through JDBC driver)
        if connected:
            if ssl_enabled:
                message = Text(f"Reachability to \"{server}\" succeeded over SSL!")
                progress.log(Panel.fit(message, style="bold green"))

                # # If SSL connections were successful, then cipher passed
                # self.output_cipher(conn_result.get_cipher_name(),
                #                    conn_result.get_protocol_version_name(), progress)
            else:
                message = Text(f"Reachability to \"{server}\" succeeded!")
                progress.log(Panel.fit(message, style="bold green"))

            if display_rtt:
                self.output_latency(rtt, progress)
        else:
            if not ssl_enabled:
                message = Text(f"Reachability to \"{server}\" failed!\n"
                               f"Please check configuration in Property Files")
                progress.log(Panel.fit(message, style="bold red"))

        return connected

    # Output cipher for the supplied connection
    @staticmethod
    def output_cipher(cipher, protocol, progress):
        message = Text(f"SSL protocol used: \"{protocol}\", is supported!", style="bold green")
        progress.log()
        progress.log(message)

        message = Text(f"SSL cipher used: \"{cipher}\", is accepted!", style="bold green")
        progress.log()
        progress.log(message)

    # Output latency for the supplied connection
    @staticmethod
    def output_latency(rtt, progress):

        max_time = 30
        min_time = 10

        if rtt < min_time:
            message = f"Acceptable Latency Range: 0ms - {min_time}ms"
            style = "bold green"
        elif min_time < rtt < max_time:
            message = f"Performance Degradation Latency Range: {min_time}ms - {max_time}ms"
            style = "bold yellow"
        else:
            message = f"Potential Failure Latency Range: > {max_time}ms"
            style = "bold red"

        progress.log()
        progress.log(Panel.fit(Text("Detected Connection Latency: {:.2f}ms \n"
                          "{}".format(rtt, message), style=style), style=style))
        progress.log()

    def validate_vector_databases(self,task2,progress):

        vectordb_ids = self._vector_db_prop["_vector_database_ids"]
        if not vectordb_ids:
            progress.log()
            progress.log(Panel.fit(Text("No Vector Databases configured in the property files, skipping Vector Database validation.", style="bold yellow")))
            self._logger.info("No Vector Databases configured in the property files, skipping Vector Database validation.")
            return True


        for vectordb_id in vectordb_ids:
            try:
                progress.log(Panel.fit(Text(f"Validating Vector Database: {vectordb_id}"), style="bold cyan"))
                progress.log()

                url = self._vector_db_prop[vectordb_id]["DATABASE_URL"],
                ssl_enabled = self._vector_db_prop[vectordb_id]['DATABASE_SSL_ENABLED']
                auth_type = self._vector_db_prop[vectordb_id]["DATABASE_AUTH_TYPE"]


                ssl_cert_folder = os.path.join(os.getcwd(), "propertyFile", self._namespace, "ssl-certs")
                vectordb_cert_folder = os.path.join(ssl_cert_folder, vectordb_id.lower())
                oidc_cert_folder = os.path.join(ssl_cert_folder, f"{vectordb_id.lower()}-oidc")


                # Need to break down URL
                # Break down the URL to get the server name and port
                db_url = url[0] if isinstance(url, tuple) else url
                if not db_url:
                    progress.log(Panel.fit(Text(f"Vector Database URL is not configured for {vectordb_id}."), style="bold red"))
                    self.is_validated[vectordb_id] = False
                    progress.advance(task2)
                    continue

                db_url_parts = urlparse(db_url)
                db_servername = db_url_parts.hostname
                db_port = db_url_parts.port

                if os.path.exists(vectordb_cert_folder):
                    progress.log(Text("Processing and combining Vector Database SSL certificate files from folder", style="bold cyan"))
                    progress.log()

                    cert, san_list = clean_and_combine_pem_files(self._logger, vectordb_cert_folder, self._TMP_DIR, db_servername)
                    self._logger.info(f"Using certificate: {cert}")
                    self._logger.info(f"Using sanlist: {san_list}")

                    progress.log(Text("Validating subject alternative names (SAN) in the certificate", style="bold cyan"))
                    progress.log()

                    if not san_list:
                        progress.log(Panel.fit(Text(f"No Subject Alternative Names found in the certificate for Vector Database ID: {vectordb_id}.\n"
                                                    "Certificate must contain Subject Alternative Names (SAN) for proper validation.\n"
                                                    f"Please check the certificate."), style="bold red"))
                        self.is_validated[vectordb_id] = False
                        progress.advance(task2)
                        return False

                    if db_servername not in san_list:
                        progress.log(Panel.fit(Text(f"Server name \"{db_servername}\" not found in the certificate SANs for Vector Database ID: {vectordb_id}.\n"
                                                    "Certificate must contain Subject Alternative Names (SAN) for proper validation.\n"
                                                    f"Please check the certificate."), style="bold red"))
                        self.is_validated[vectordb_id] = False
                        progress.advance(task2)
                        return False

                    self._logger.info(f"Server name \"{db_servername}\" found in the certificate SANs for Vector Database ID: {vectordb_id}.")
                    progress.log(Text("Subject Alternative Names (SAN) found in the certificate"), style="bold green")
                    progress.log()
                    progress.log(Text(f"Server name \"{db_servername}\" found in the certificate SANs for Vector Database ID: {vectordb_id}.", style="bold green"))
                    progress.log()


                    # Checking the OIDC certificate if provided
                    # Only need to check if OIDC is used
                    if self._vector_db_prop[vectordb_id]["DATABASE_AUTH_TYPE"].lower() == "oidc":

                        # Get the token URL to extract the server name
                        token_url = self._vector_db_prop[vectordb_id]["DATABASE_OIDC_ENDPOINT"]
                        if not token_url:
                            progress.log(Panel.fit(Text(f"OIDC is configured for Vector Database ID: {vectordb_id}, but no OIDC token endpoint found.\n"
                                                        "Please check the OIDC configuration in the cas_vector_database.toml file."), style="bold red"))
                            self.is_validated[vectordb_id] = False
                            progress.advance(task2)
                            return False

                        token_url_parts = urlparse(token_url)
                        token_servername = token_url_parts.hostname
                        self._logger.info(f"OIDC token endpoint server name: {token_servername} for Vector Database ID: {vectordb_id}")

                        if not os.path.exists(oidc_cert_folder):
                            progress.log(Panel.fit(Text(f"OIDC is configured for Vector Database ID: {vectordb_id}, but no OIDC certificate found.\n"
                                                        "Please check the certificate."), style="bold red"))
                            self.is_validated[vectordb_id] = False
                            progress.advance(task2)
                            return False

                        # If OIDC certificate is provided, need to check the SANs as well
                        oidc_cert, san_list = clean_and_combine_pem_files(self._logger, oidc_cert_folder, self._TMP_DIR, token_servername)

                        self._logger.info(f"Using OIDC certificate: {oidc_cert} for Vector Database ID: {vectordb_id}")
                        progress.log(Text("Processing and combining Vector Database OIDC SSL certificate files from folder",
                                 style="bold cyan"))
                        progress.log()



                        self._logger.info(f"Using OIDC certificate: {oidc_cert}")
                        self._logger.info(f"Using OIDC sanlist: {san_list}")

                        progress.log(Text("Validating subject alternative names (SAN) in the OIDC certificate", style="bold cyan"))
                        progress.log()

                        if not san_list:
                            progress.log(Panel.fit(Text(f"No Subject Alternative Names found in the OIDC certificate for Vector Database ID: {vectordb_id}.\n"
                                                        "OIDC Certificate must contain Subject Alternative Names (SAN) for proper validation.\n"
                                                        f"Please check the certificate."), style="bold red"))
                            self.is_validated[vectordb_id] = False
                            progress.advance(task2)
                            return False

                        if token_servername not in san_list:
                            progress.log(Panel.fit(Text(f"OIDC token endpoint server name \"{token_servername}\" not found in the OIDC certificate SANs for Vector Database ID: {vectordb_id}.\n"
                                                        "OIDC Certificate must contain Subject Alternative Names (SAN) for proper validation.\n"
                                                        f"Please check the certificate."), style="bold red"))
                            self.is_validated[vectordb_id] = False
                            progress.advance(task2)
                            return False

                        self._logger.info(f"OIDC token endpoint server name \"{token_servername}\" found in the OIDC certificate SANs for Vector Database ID: {vectordb_id}.")
                        progress.log(Text("Subject Alternative Names (SAN) found in the OIDC certificate"), style="bold green")
                        progress.log()
                        progress.log(Text(f"OIDC token endpoint server name \"{token_servername}\" found in the OIDC certificate SANs for Vector Database ID: {vectordb_id}.", style
                                    ="bold green"))
                        progress.log()

                    else:
                        oidc_cert = None

                else:
                    cert = None
                    oidc_cert = None

                connected = True
                if ssl_enabled:

                    connected = self.validate_server(progress=progress, server=db_servername, port=db_port,
                                                     ssl_enabled=ssl_enabled,
                                                     display_rtt=True, cert_path=cert)

                    if not connected:
                        progress.log(Text(f"Reachability over SSL failed. Attempting connection without certificate verification."),
                            style="bold yellow")
                        progress.log()

                        connected = self.validate_server(progress=progress, server=db_servername, port=db_port,
                                                         ssl_enabled=False, display_rtt=True)
                else:
                    connected = self.validate_server(progress=progress, server=db_servername, port=db_port,
                                                     ssl_enabled=ssl_enabled,
                                                     display_rtt=True)

                if not connected:
                    self.is_validated[vectordb_id] = connected
                    progress.advance(task2)
                    return connected

                connected_str = Text(f"Successfully connected to vector database ID \"{vectordb_id}\"!", style="bold green")
                not_connected_str = Text(f"Unable to connect to database ID \"{vectordb_id}\" " \
                                         + f"on database server \"{db_servername}\", " \
                                         + "please check database toml file again.", style="bold red")


                # Validate the OIDC endpoint reachability if OIDC is used
                if auth_type.lower() == "oidc":
                    token_url = self._vector_db_prop[vectordb_id].get("DATABASE_OIDC_ENDPOINT", None)
                    if not token_url:
                        progress.log(Panel.fit(Text(f"OIDC is configured for Vector Database ID: {vectordb_id}, but no OIDC token endpoint found.\n"
                                                    "Please check the OIDC configuration in the cas_vector_database.toml file."), style="bold red"))
                        self.is_validated[vectordb_id] = False
                        progress.advance(task2)
                        return False

                    token_url_parts = urlparse(token_url)
                    token_servername = token_url_parts.hostname
                    token_port = token_url_parts.port if token_url_parts.port else (443 if token_url_parts.scheme == "https" else 80)

                    self._logger.info(f"Validating OIDC endpoint server name: {token_servername} and port: {token_port} for Vector Database ID: {vectordb_id}")

                    oidc_connected = True
                    if ssl_enabled:
                        oidc_connected = self.validate_server(progress=progress, server=token_servername, port=token_port,
                                                         ssl_enabled=ssl_enabled,
                                                         display_rtt=True, cert_path=oidc_cert)

                        if not oidc_connected:
                            progress.log(Text(f"OIDC endpoint reachability over SSL failed. Attempting connection without certificate verification."),
                                style="bold yellow")
                            progress.log()

                            oidc_connected = self.validate_server(progress=progress, server=token_servername, port=token_port,
                                                             ssl_enabled=False, display_rtt=True)
                    else:
                        oidc_connected = self.validate_server(progress=progress, server=token_servername, port=token_port,
                                                         ssl_enabled=ssl_enabled,
                                                         display_rtt=True)

                    if not oidc_connected:
                        self.is_validated[vectordb_id] = oidc_connected
                        progress.advance(task2)
                        return oidc_connected

                validated = self.validate_vector_database_endpoint(db_id=vectordb_id,
                                                                   auth_type=self._vector_db_prop[vectordb_id]["DATABASE_AUTH_TYPE"],
                                                                   task=task2,
                                                                   progress=progress,
                                                                   cert=cert,
                                                                   oidc_cert=oidc_cert)

                if validated:
                    progress.log(Panel.fit(connected_str))
                    progress.log()
                    self._logger.info(f"Successfully connected to vector database ID \"{vectordb_id}\"!")
                    self.is_validated[vectordb_id] = True
                else:
                    progress.log(Panel.fit(not_connected_str, style="bold red"))
                    progress.log()
                    self._logger.info(f"Unable to connect to vector database ID \"{vectordb_id}\" on database server \"{db_servername}\", please check database toml file again.")
                    self.is_validated[vectordb_id] = False

                progress.advance(task2)
                return self.is_validated[vectordb_id]
            except Exception as e:
                progress.log(Panel.fit(Text(f"Failed to validate Vector Database: {vectordb_id}"), style="bold red"))
                progress.log()
                self._logger.info(f"Failed to validate Vector Database: {vectordb_id}! Error: {str(e)}")
                self.is_validated[vectordb_id] = False
                progress.advance(task2)
                return False