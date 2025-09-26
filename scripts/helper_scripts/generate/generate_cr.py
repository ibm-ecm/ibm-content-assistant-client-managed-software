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
import os
from urllib.parse import urlparse

from ruamel.yaml import CommentedMap
from ruamel.yaml import YAML

from ..utilities.prerequisites_utilites import collect_visible_files


# Function to remove protocol from URL
def remove_protocol(url):
    hostname = urlparse(url).hostname
    if hostname is None:
        hostname = url
    return hostname


# Class to generate the CR
class GenerateCR:

    # read to yaml function
    def load_cr_template(self, filepath):
        # load the YAML file with comments
        # read the source YAML file with comments
        with open(filepath, 'r') as file:
            data = YAML()
            data.preserve_quotes = True
            data = data.load(file)
        return data

    # write to yaml function
    def write_cr_template(self):
        # write the updated YAML file with preserved comments
        with open(self._generated_cr, 'w') as file:
            yaml = YAML()
            yaml.representer.ignore_aliases = lambda *args: True
            yaml.dump(self._merged_data, file)

    def __init__(self, namespace, content_assistant_properties=None, vector_database_properties=None, deployment_properties=None,ingress_properties=None,
                 logger=None):
        self._logger = logger

        self._content_assistant_properties = content_assistant_properties
        self._vector_database_properties = vector_database_properties
        self._deployment_properties = deployment_properties
        self._ingress_properties = ingress_properties

        self._generate_folder = os.path.join(os.getcwd(), "generatedFiles", namespace)
        # Navigate up two levels to the parent directory
        self._base_template = os.path.join(os.getcwd(), "helper_scripts", "generate", "cr_templates",
                                           self._deployment_properties["CAS_VERSION"], "base.yaml")
        self._cas_configuration_template = os.path.join(os.getcwd(), "helper_scripts", "generate", "cr_templates",
                                           self._deployment_properties["CAS_VERSION"], "cas_configuration.yaml")
        self._vector_database_template = os.path.join(os.getcwd(), "helper_scripts", "generate", "cr_templates",
                                           self._deployment_properties["CAS_VERSION"], "vector_database.yaml")
        self._ingress_template = os.path.join(os.getcwd(), "helper_scripts", "generate", "cr_templates",
                                          self._deployment_properties["CAS_VERSION"], "ingress.yaml")
        self._egress_template = os.path.join(os.getcwd(), "helper_scripts", "generate", "cr_templates",
                                          self._deployment_properties["CAS_VERSION"], "egress.yaml")

        self._generated_cr = os.path.join(self._generate_folder, "ibm_content_assistant_cr.yaml")
        self._merged_data = CommentedMap()
        if os.path.exists(self._generated_cr):
            os.remove(self._generated_cr)

    def generate_cr(self):
        self._logger.info("generating CR")
        # call function to generate shared configuration section of CR
        self.generate_base_section()

        if self._vector_database_properties:
            self.populate_vector_database_section()

        self.populate_ingress_section()

        if self._deployment_properties["PLATFORM"] == "other" and self._deployment_properties["GENERATE_NETWORK_POLICIES"]:
            self.populate_egress_section()


        self.write_cr_template()


    # Create a function to generate the OIDC section
    def populate_idp_section(self):
        self._logger.info("generating OIDC section")
        try:
            idp_section = self.load_cr_template(self._idp_template)
            num_idp = len(self._idp_properties["_idp_ids"])

            # Adding the OIDC section to the CR
            # First section already exists in the template
            # Loop to add additional sections
            while len(idp_section["spec"]["shared_configuration"]["open_id_connect_providers"]) < num_idp:
                new_idp_dict = idp_section["spec"]["shared_configuration"]["open_id_connect_providers"][0].copy()
                idp_section["spec"]["shared_configuration"]["open_id_connect_providers"].append(new_idp_dict)

            # Populate the OIDC section
            # Loop through idp_properties and populate the OIDC section
            for idx, key in enumerate(self._idp_properties["_idp_ids"]):
                secret_name = "ibm-" + key.lower() + "-oidc-secret"

                # Create OIDC secret section

                idp_section["spec"]["shared_configuration"]["open_id_connect_providers"][idx]["provider_name"] = key
                idp_section["spec"]["shared_configuration"]["open_id_connect_providers"][idx]["display_name"] = \
                    self._idp_properties[key]["DISPLAY_NAME"]
                idp_section["spec"]["shared_configuration"]["open_id_connect_providers"][idx]["issuer_identifier"] = \
                    self._idp_properties[key]["ISSUER"]

                secret_section = {"cpe": secret_name, "nav": secret_name}
                if self._deployment_properties["FNCM_Version"] == "5.5.8":
                    secret_section["es"] = secret_name
                    secret_section["graphql"] = secret_name

                idp_section["spec"]["shared_configuration"]["open_id_connect_providers"][idx][
                    "client_oidc_secret"] = secret_section
                idp_section["spec"]["shared_configuration"]["open_id_connect_providers"][idx]["validation_method"] = \
                    self._idp_properties[key]["VALIDATION_METHOD"]
                idp_section["spec"]["shared_configuration"]["open_id_connect_providers"][idx]["user_identifier"] = \
                    self._idp_properties[key]["USER_IDENTIFIER"]
                idp_section["spec"]["shared_configuration"]["open_id_connect_providers"][idx][
                    "unique_user_identifier"] = \
                    self._idp_properties[key]["UNIQUE_USER_IDENTIFIER"]
                idp_section["spec"]["shared_configuration"]["open_id_connect_providers"][idx][
                    "user_identity_to_create_subject"] = \
                    self._idp_properties[key]["USER_IDENTIFIER_TO_CREATE_SUBJECT"]
                idp_section["spec"]["shared_configuration"]["open_id_connect_providers"][idx]["token_endpoint_url"] = \
                    self._idp_properties[key]["TOKEN_ENDPOINT"]

                if "DISCOVERY_ENDPOINT" in self._idp_properties[key]:
                    idp_section["spec"]["shared_configuration"]["open_id_connect_providers"][idx][
                        "discovery_endpoint_url"] = \
                        self._idp_properties[key]["DISCOVERY_ENDPOINT"]
                else:
                    idp_section["spec"]["shared_configuration"]["open_id_connect_providers"][idx].pop(
                        "discovery_endpoint_url")

                # Build custom user-defined parameters
                parameter_list = []
                if self._idp_properties[key]["VALIDATION_METHOD"] == "userinfo":
                    parameter = "DELIM=;userinfoEndpointUrl;" + self._idp_properties[key]["USERINFO_ENDPOINT"]
                    parameter_list.append(parameter)
                    parameter = "DELIM=;userinfo;true"
                    parameter_list.append(parameter)
                else:
                    parameter = "DELIM=;introspectEndpointUrl;" + self._idp_properties[key]["INTROSPECT_ENDPOINT"]
                    parameter_list.append(parameter)

                if "REVOCATION_ENDPOINT" in self._idp_properties[key]:
                    parameter = "DELIM=;revokeEndpointUrl;" + self._idp_properties[key]["REVOCATION_ENDPOINT"]
                    parameter_list.append(parameter)

                # Add custom user-defined parameters to the OIDC section
                idp_section["spec"]["shared_configuration"]["open_id_connect_providers"][idx][
                    "oidc_ud_param"] = parameter_list

            self._merged_data["spec"]["shared_configuration"].update(idp_section["spec"]["shared_configuration"])

        except Exception as e:
            self._logger.exception(f"Error found in populate-idp function in generate_cr script --- {str(e)}")



    # function to generate the shared section
    def generate_base_section(self):
        self._logger.info("Generating Base section")
        try:
            base_dict = self.load_cr_template(self._base_template)

            base_dict["spec"]["license"]["accept"] = True
            base_dict["spec"]["shared_configuration"]["sc_deployment_platform"] = self._deployment_properties["PLATFORM"]


            # update trusted certificates parameter if we have secrets generated
            if os.path.exists(os.path.join(self._generate_folder, "ssl", "trusted-certs")):
                trusted_cert_secrets = collect_visible_files(
                    os.path.join(self._generate_folder, "ssl", "trusted-certs"))
                for secret in trusted_cert_secrets:
                    secret_name = secret.split(".")[0]
                    base_dict["spec"]["shared_configuration"]["trusted_certificate_list"].append(
                        secret_name)

            # Add the certs for IDP and SCIM
            # These secrets are added generated ssl folder

            if os.path.exists(os.path.join(self._generate_folder, "ssl")):
                ssl_cert_secrets = collect_visible_files(
                    os.path.join(self._generate_folder, "ssl"))
                for secret in ssl_cert_secrets:
                    # check if the secret is related to idp or scim
                    # check if the secret name contains idp or oidc
                    if "idp" in secret.lower()  or "scim" in secret.lower():
                        secret_name = secret.split(".")[0]
                        base_dict["spec"]["shared_configuration"]["trusted_certificate_list"].append(
                            secret_name)

            # when roks is enabled we need to have an ingress parameter set to false
            if self._deployment_properties["PLATFORM"].lower() == "roks":
                base_dict["spec"]["shared_configuration"]["sc_ingress_enable"] = False
            base_dict["spec"]["shared_configuration"]["sc_cas_license_type"] = self._deployment_properties["LICENSE"]
            # For now it can only be fncm
            base_dict["spec"]["shared_configuration"]["sc_cas_license_type"] = "fncm"
            base_dict["spec"]["shared_configuration"]["storage_configuration"][
                "sc_slow_file_storage_classname"] = self._deployment_properties["SLOW_FILE_STORAGE_CLASSNAME"]

            base_dict["spec"]["shared_configuration"]["sc_generate_sample_network_policies"] = self._deployment_properties["GENERATE_NETWORK_POLICIES"]

            self._merged_data.update(base_dict)


        except Exception as e:
            self._logger.exception(
                f"Error found in generate_base_section function in generate_cr script --- {str(e)}")

    # function to generate the Vector Database section
    def populate_vector_database_section(self):
        self._logger.info("Populating Vector Database section")
        try:
            vector_database_dict = self.load_cr_template(self._vector_database_template)
            vector_database_id = self._vector_database_properties["_vector_database_ids"][0]
            vector_database_dict["spec"]["vector_database"]["vector_database_url"] = self._vector_database_properties[vector_database_id]["DATABASE_URL"]
            vector_database_dict["spec"]["vector_database"]["vector_database_auth_type"] = self._vector_database_properties[vector_database_id]["DATABASE_AUTH_TYPE"]
            if self._vector_database_properties[vector_database_id]["DATABASE_AUTH_TYPE"].lower() == "basicauth":
                vector_database_dict["spec"]["vector_database"].pop("vector_database_oidc_token_endpoint")
                vector_database_dict["spec"]["vector_database"].pop("vector_database_oidc_certificate")
            else:
                vector_database_dict["spec"]["vector_database"]["vector_database_oidc_token_endpoint"] = self._vector_database_properties[vector_database_id]["DATABASE_OIDC_ENDPOINT"]
            vector_database_dict["spec"]["vector_database"]["vector_database_ssl_enabled"] = self._vector_database_properties[vector_database_id]["DATABASE_SSL_ENABLED"]
            vector_database_dict["spec"]["vector_database"]["vector_database_type"] = self._vector_database_properties[vector_database_id]["DATABASE_TYPE"]

            self._merged_data["spec"].update(vector_database_dict["spec"])



        except Exception as e:
            self._logger.exception(
                f"Error found in generate_vector_database function in generate_cr script --- {str(e)}")


    # Function to generate the content assistant section
    def populate_cas_section(self):
        self._logger.info("Populating IBM Content Assistant configuration section")
        try:
            cas_configuration_dict = self.load_cr_template(self._cas_configuration_template)
            self._merged_data["spec"].update(cas_configuration_dict["spec"])


        except Exception as e:
            self._logger.exception(
                f"Error found in populate cas section function in generate_cr script --- {str(e)}")

    # function to generate the ingress section
    def populate_ingress_section(self):
        # populate ingress section
        # if ingress properties are created then we populate them
        if self._ingress_properties:
            ingress_dict = self.load_cr_template(self._ingress_template)
            ingress_dict["spec"]["shared_configuration"]["sc_service_type"] = self._ingress_properties[
                "SERVICE_TYPE"]
            ingress_dict["spec"]["shared_configuration"]["sc_ingress_enable"] = \
                self._ingress_properties["INGRESS_ENABLED"]
            if self._ingress_properties["INGRESS_TLS_ENABLED"]:
                if 'INGRESS_TLS_SECRET_NAME' in self._ingress_properties and self._ingress_properties[
                    "INGRESS_TLS_SECRET_NAME"].lower() != "<optional>":
                    ingress_dict["spec"]["shared_configuration"]["sc_ingress_tls_secret_name"] = \
                        self._ingress_properties["INGRESS_TLS_SECRET_NAME"]
                else:
                    ingress_dict["spec"]["shared_configuration"].pop("sc_ingress_tls_secret_name")
            else:
                ingress_dict["spec"]["shared_configuration"].pop("sc_ingress_tls_secret_name")
            ingress_dict["spec"]["shared_configuration"]["sc_ingress_annotations"] = []
            if self._ingress_properties["INGRESS_ANNOTATIONS"] and self._ingress_properties["INGRESS_ANNOTATIONS"] is not None:
                ingress_annotation = {}
                for item in self._ingress_properties["INGRESS_ANNOTATIONS"]:
                    item_key = item.split(":", 1)[0]
                    item_value = item.split(":", 1)[1]
                    # Remove leading/trailing whitespace and single quotes from the key and value
                    item_key = item_key.strip()
                    item_value = item_value.strip().strip('"').strip("\\'")
                    ingress_annotation[item_key] = item_value
            else:
                ingress_annotation = {}
            ingress_dict["spec"]["shared_configuration"]["sc_ingress_annotations"] = ingress_annotation
            ingress_dict["spec"]["shared_configuration"]["sc_deployment_hostname_suffix"] = \
                remove_protocol(self._ingress_properties["INGRESS_HOSTNAME"].lower())

            self._merged_data["spec"]["shared_configuration"].update(ingress_dict["spec"]["shared_configuration"])

        # else:
        #     ingress_params = ["sc_service_type", "sc_ingress_enable", "sc_ingress_tls_secret_name",
        #                       "sc_deployment_hostname_suffix", "sc_ingress_annotations"]
        #     for param in ingress_params:
        #         if param in self._merged_data["spec"]["shared_configuration"].keys():
        #             self._merged_data["spec"]["shared_configuration"].pop(param)
    
    # function to generate the egress section
    def populate_egress_section(self):        
        egress_dict = self.load_cr_template(self._egress_template)
        if "K8_API_NAMESPACE" in self._deployment_properties.keys():
            egress_dict["spec"]["shared_configuration"]["sc_egress_configuration"]["sc_api_namespace"] = self._deployment_properties[
                "K8_API_NAMESPACE"]
        else:
            egress_dict["spec"]["shared_configuration"]["sc_egress_configuration"].pop("sc_api_namespace")
        if "K8_API_PORT" in self._deployment_properties.keys():
            egress_dict["spec"]["shared_configuration"]["sc_egress_configuration"]["sc_api_port"] = \
                self._deployment_properties["K8_API_PORT"]
        else:
            egress_dict["spec"]["shared_configuration"]["sc_egress_configuration"].pop("sc_api_port")
        if "K8_DNS_NAMESPACE" in self._deployment_properties.keys():
            egress_dict["spec"]["shared_configuration"]["sc_egress_configuration"]["sc_dns_namespace"] = \
                self._deployment_properties["K8_DNS_NAMESPACE"]
        else:
            egress_dict["spec"]["shared_configuration"]["sc_egress_configuration"].pop("sc_dns_namespace")
        if "K8_DNS_PORT" in self._deployment_properties.keys():
            egress_dict["spec"]["shared_configuration"]["sc_egress_configuration"]["sc_dns_port"] = \
                self._deployment_properties["K8_DNS_PORT"]
        else:
            egress_dict["spec"]["shared_configuration"]["sc_egress_configuration"].pop("sc_dns_port")
        
        if egress_dict["spec"]["shared_configuration"]["sc_egress_configuration"].keys():
            self._merged_data["spec"]["shared_configuration"].update(egress_dict["spec"]["shared_configuration"])


