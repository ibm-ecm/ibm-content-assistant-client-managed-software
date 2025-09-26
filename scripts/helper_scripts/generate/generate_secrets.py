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
import os
import shutil

import jinja2
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from ..utilities.prerequisites_utilites import collect_visible_files, split_pem, encode_secret_contents, \
    generate_secure_password


# Class to generate secrets
class GenerateSecrets:
    _TMP_DIR = os.path.join(os.getcwd(), "helper_scripts", "generate", "tmp")

    def __init__(self, namespace, content_assistant_properties=None,vector_database_properties=None,logger=None):
        self._logger = logger

        self._content_assistant_properties = content_assistant_properties
        self._vector_database_properties = vector_database_properties


        self._ssl_cert_folder = os.path.join(os.getcwd(), "propertyFile", namespace, "ssl-certs")
        self._trusted_certs_folder = os.path.join(self._ssl_cert_folder, "trusted-certs")


        self._generate_folder = os.path.join(os.getcwd(), "generatedFiles", namespace)
        self._generate_secrets_folder = os.path.join(self._generate_folder, "secrets")
        self._generate_ssl_secrets_folder = os.path.join(self._generate_folder, "ssl")
        self._generate_trusted_secrets_folder = os.path.join(self._generate_ssl_secrets_folder, "trusted-certs")

        self._secret_template_folder = os.path.join(os.getcwd(), "helper_scripts", "generate", "templates")


        # Load all jinja templates
        self._template_loader = jinja2.FileSystemLoader(self._secret_template_folder)
        self._template_env = jinja2.Environment(loader=self._template_loader, trim_blocks=True)

        self.__create_tmp_folder()

    def __create_tmp_folder(self):
        try:
            if not os.path.exists(self._TMP_DIR):
                os.makedirs(self._TMP_DIR)
            else:
                self._logger.info(f"The folder {self._TMP_DIR} already exists")
                # Delete and recreate the TMP folder 
                shutil.rmtree(self._TMP_DIR)
                os.makedirs(self._TMP_DIR)
        except Exception as e:
            self._logger.exception(
                f"Exception from validate.py script in function -  {str(e)}")
        return self._TMP_DIR

    # Function to XOR password
    def xor_password(self, data, xorkey=0x5F):
        """XORs a password with a key.The key used here is _"""

        # Convert password to bytes
        password_bytes = data.encode()

        # XOR each byte of the password with the key
        xor_result_bytes = bytes([b ^ xorkey for b in password_bytes])

        # Encode the XORed bytes using base64
        xor_encoded_bytes = base64.b64encode(xor_result_bytes)

        # Convert the encoded bytes to a string and prepend with "{xor}"
        xor_result_string = "{xor}" + xor_encoded_bytes.decode()
        return xor_result_string

    def render_ssl_secret_template(self, values, secret_name):
        """
        Renders an SSL secret template using the provided values and secret name.

        Parameters:
        values (dict): A dictionary containing the variables to be substituted in the template.
        secret_name (str): The name of the secret to be created.

        Returns:
        str: The rendered secret content for the secret.
        """
        template = self._template_env.get_template('secret.j2')

        # Render the template with the provided values
        rendered_secret = template.render(
            values=values,
            secret_name=secret_name)

        return rendered_secret

    def render_secret_template(self, values, secret_name):
        """
        Renders a Jinja2 template for a secret with the provided values.

        Parameters:
        values (dict): A dictionary containing the variable values to be substituted in the template.
        secret_name (str): The name of the secret to be used in the template.

        Returns:
        str: The rendered secret string.
        """
        # Get the template from the environment
        template = self._template_env.get_template('secret.j2')

        # Render the template with the provided values
        rendered_secret = template.render(
            values=values,
            secret_name=secret_name
        )

        return rendered_secret

    def create_ssl_secret(self, folderpath, ssl_certs, item, prefix="cert-"):
        """
        This function creates an SSL secret from a list of certificate files.

        Parameters:
        folderpath (str): The path to the folder containing the SSL certificate files.
        ssl_certs (list): A list of certificate file names (without extension) to be included in the secret.
        item (str): A unique identifier for the secret.

        Returns:
        None

        The function reads each certificate file in the provided folder, splits multi-file PEM certificates,
        encodes the certificate data in base64, and writes it into a YAML secret file. The secret file is
        named using the format "ibm-<item>-ssl-secret.yaml" and is saved in the directory specified by
        `_generate_ssl_secrets_folder`. The function also logs the creation of the secret.
        """
        data = ""
        for i, cert in enumerate(ssl_certs):
            if any(ext in cert for ext in [".crt", ".cer", ".pem", ".cert", ".key", ".arm"]):
                certfolderpath = os.path.join(folderpath, cert)
                # Split the certificate to separate files
                cert_list = split_pem(self._logger, certfolderpath, self._TMP_DIR, f'{prefix}{i}')

                for k, cert in enumerate(cert_list):
                    self._logger.info("Reading the file " + cert)
                    # Read binary data from SSL certificate file
                    with open(cert, "r") as file:
                        cert_data = file.read()
                    # Append the encoded data to the encoded_data variable
                    data = data + cert_data + '\n'

        # Encode the certificate to base64 
        encoded_data = base64.b64encode(data.encode()).decode('utf-8')
        secret_name = item
        secret_filename = secret_name + ".yaml"
        sslsecret_filepath = os.path.join(self._generate_ssl_secrets_folder, secret_filename)


        data = {
            'tls.crt': encoded_data,
        }

        rendered_secret = self.render_ssl_secret_template(data, secret_name)

        # write the secret data into a yaml
        with open(sslsecret_filepath, 'w+') as file:
            file.write(rendered_secret)
            self._logger.info(f"Created ssl secret: {secret_name}")

    def generate_encrypted_private_key(self):
        # Generate a random password
        password = generate_secure_password()

        # 2. Generate RSA private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,  # you can use 4096 for stronger keys
            backend=default_backend()
        )

        # 3. Serialize with encryption
        pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,  # gives "ENCRYPTED PRIVATE KEY"
            encryption_algorithm=serialization.BestAvailableEncryption(password.encode())
        )
        return password, pem.decode("utf-8")

    def create_component_secret(self, data, secret_name,secret_folder):
        """
        Creates a Kubernetes secret from a given dictionary of data and a secret name.

        Args:
        data (dict): A dictionary containing the data to be included in the secret.
        secret_name (str): The name to be given to the created secret.

        Returns:
        None

        The function generates a filename for the secret by appending ".yaml" to the secret name.
        It then constructs the full file path by joining the generated filename with the secrets folder path.

        The function renders a secret template using the provided data and secret name.

        Finally, it writes the rendered secret data into a YAML file at the specified file path.
        A logging message is also printed to indicate the creation of the component secret.
        """
        secret_filename = secret_name + ".yaml"
        secret_filepath = os.path.join(secret_folder, secret_filename)

        # This function makes sure all values are encoded in base64 so that we can create templates with data and not string data
        encoded_secret_data = encode_secret_contents(data)

        rendered_secret = self.render_secret_template(encoded_secret_data, secret_name)

        # write the secret data into a yaml
        with open(secret_filepath, 'w+') as file:
            file.write(rendered_secret)
            self._logger.info(f"Created component secret: {secret_name}")

    # function to create content assistant secret
    def create_content_assistant_secret(self):
        self._logger.info("Creating IBM Content Assistant secret")

        secret_name = "ibm-content-assistant-secret"

        data = {}

        for ai_provider in self._content_assistant_properties["_ai_providers_ids"]:
            ai_provider_label = self._content_assistant_properties[ai_provider]["AI_PROVIDER_LABEL"]
            data[f"AI_PROVIDER_API_KEY_{ai_provider_label.upper()}"] = self._content_assistant_properties[ai_provider]["API_KEY"]
            data[f"AI_PROVIDER_SPACE_ID_{ai_provider_label.upper()}"] = self._content_assistant_properties[ai_provider]["SPACE_ID"]

        self.create_component_secret(data, secret_name,self._generate_secrets_folder)

    # function to create content assistant secret
    def create_vector_database_secret(self, id="VECTORDB",database_number=1):
        self._logger.info("Creating IBM Content Assistant secret")

        if database_number == 1:
            secret_name = "vector-database-secret"
        else:
            secret_name = f"vector-database-{database_number}-secret"

        data = {}
        data["VECTOR_DATABASE_USER_ID"] = self._vector_database_properties[id]['DATABASE_USERNAME']
        data["VECTOR_DATABASE_USER_PASSWORD"] = self._vector_database_properties[id][
            'DATABASE_USER_PASSWORD']
        if self._vector_database_properties[id]['DATABASE_AUTH_TYPE'].lower() == "oidc":
            data["VECTOR_DATABASE_OIDC_TOKEN_ENDPOINT"] = self._vector_database_properties[id][
                'DATABASE_OIDC_ENDPOINT']
            data["VECTOR_DATABASE_OIDC_CLIENT_ID"] = self._vector_database_properties[id][
                'DATABASE_OIDC_CLIENT_ID']
            data["VECTOR_DATABASE_OIDC_CLIENT_SECRET"] = self._vector_database_properties[id][
                'DATABASE_OIDC_CLIENT_SECRET']

        self.create_component_secret(data, secret_name,self._generate_secrets_folder)

    # function to create the vector database ssl secret
    def create_vector_database_ssl_secret(self,id="VECTORDB"):

        vector_database_folder = os.path.join(self._ssl_cert_folder, id.lower())
        if os.path.exists(vector_database_folder):
            self._logger.info(f"Creating vector database ssl secret for Vector Database ID: {id} ")

            ssl_certs = collect_visible_files(vector_database_folder)
            if id.lower() == "vectordb":
                secret_name = "vector-database-certificate-secret"
            else:
                secret_name = "vector_database-2-certificate-secret"
            self.create_ssl_secret(folderpath=vector_database_folder, ssl_certs=ssl_certs, item=secret_name, prefix=f"{str(id).lower()}-")

    # function to create the vector database OIDC ssl secret
    def create_vector_database_oidc_ssl_secret(self, id="VECTORDB"):

        vector_database_oidc_folder = os.path.join(self._ssl_cert_folder,f"{str(id).lower()}-oidc")
        if os.path.exists(vector_database_oidc_folder):
            self._logger.info(f"Creating vector database OIDC ssl secret for Vector Database ID: {id} ")

            ssl_certs = collect_visible_files(vector_database_oidc_folder)
            if id.lower() == "vectordb":
                secret_name = "vector-database-oidc-certificate-secret"
            else:
                secret_name = "vector_database-2-oidc-certificate-secret"
            self.create_ssl_secret(folderpath=vector_database_oidc_folder, ssl_certs=ssl_certs, item=secret_name, prefix=f"{str(id).lower()}-oidc-")

    # Function to create the admin access secret that generates an encrypted private key first
    def create_content_admin_access_secret(self):
        self._logger.info("Creating IBM Content Assistant Admin Access ssl secret")
        passkey,private_key = self.generate_encrypted_private_key()
        secret_name = "ibm-content-assistant-admin-key-secret"

        data = {
            "admin_key.pem": private_key,
            "ACCESS_TOKEN_KEY_PASSPHRASE": passkey
        }
        self.create_component_secret(data, secret_name,self._generate_ssl_secrets_folder)

    def create_trusted_secrets(self):
        """
        This function creates Kubernetes secrets for trusted SSL certificates.

        It searches for SSL certificate files in the specified trusted certificates folder.
        It then splits the certificate files into separate files if necessary, reads their binary data,
        encodes the data in base64, and creates a Kubernetes secret for each certificate.

        Parameters:
        self (object): An instance of the class containing the method. It should have the following attributes:
            - _trusted_certs_folder (str): The path to the folder containing trusted SSL certificates.
            - _TMP_DIR (str): The path to a temporary directory.
            - _generate_trusted_secrets_folder (str): The path to the folder where the secrets will be generated.
            - _logger (logging.Logger): A logger object for logging messages.

        Returns:
        None
        """
        try:
            if not os.path.exists(self._trusted_certs_folder):
                return

            trusted_certs = collect_visible_files(self._trusted_certs_folder)

            for i, cert in enumerate(trusted_certs):
                if any(ext in cert for ext in [".crt", ".cer", ".pem", ".cert", ".key", ".arm"]):
                    certfolderpath = os.path.join(self._trusted_certs_folder, cert)
                    # Split the certificate to separate files
                    cert_list = split_pem(self._logger, certfolderpath, self._TMP_DIR, f'trusted-{i}')
                    data = ""
                    for k, split_cert in enumerate(cert_list):
                        self._logger.info("Reading the file " + split_cert)
                        # Read binary data from SSL certificate file
                        with open(split_cert, "r") as file:
                            cert_data = file.read()
                        # Append the encoded data to the encoded_data variable
                        data = data + cert_data + '\n'

                # Encode the certificate to base64 
                encoded_data = base64.b64encode(data.encode()).decode('utf-8')
                secret_name = f"trusted-cert-{i + 1}-secret"
                secret_filename = f"{secret_name}.yaml"
                sslsecret_filepath = os.path.join(self._generate_trusted_secrets_folder, secret_filename)

                data = {
                    'tls.crt': encoded_data,
                }

                rendered_secret = self.render_ssl_secret_template(data, secret_name)

                # write the secret data into a yaml
                with open(sslsecret_filepath, 'w+') as file:
                    file.write(rendered_secret)
                    self._logger.info(f"Created trusted secret: {secret_name}")
        except Exception as e:
            self._logger.exception(
                f"Error found in create_trusted_secrets function in generate_secrets script --- {str(e)}")
