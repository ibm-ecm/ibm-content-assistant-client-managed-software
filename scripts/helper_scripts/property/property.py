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

import copy
import os

from tomlkit import comment
from tomlkit import document
from tomlkit import nl
from tomlkit import string
from tomlkit import table
from tomlkit.toml_file import TOMLFile

from ..utilities.prerequisites_utilites import read_json


# Create a class Property that accepts a dictionary of key value pairs
# - Create a java property file
# - Accept a current directory path
# - Create a set of containing folder
# - Backup existing property file if they exist

class Property:

    def __init__(self, gather_obj, path, logger, console):
        self._logger = logger
        self._console = console
        self._gather = gather_obj
        self._namespace = gather_obj.namespace
        self._working_directory = path
        self._property_folder = os.path.join(self._working_directory, 'propertyFile', self._namespace)
        self._ssl_directory_folder = os.path.join(self._property_folder, 'ssl-certs')
        self._trusted_certs_directory_folder = os.path.join(self._property_folder, 'ssl-certs', 'trusted-certs')

        # Create a dictionary of properties
        self._json_directory = os.path.dirname(__file__)
        self._deployment_properties = read_json(self._json_directory, "deployment_property.json")
        self._storage_properties = read_json(self._json_directory, "storage_property.json")
        self._egress_properties = read_json(self._json_directory, "egress_property.json")
        self._vector_database_properties = read_json(self._json_directory, "vector_database_property.json")
        self._content_assistant_properties = read_json(self._json_directory, "admin_access_property.json")
        self._content_assistant_watsonx_properties = read_json(self._json_directory,
                                                               "watsonx_property.json")
        self._ingress_properties = read_json(self._json_directory, "ingress_property.json")


    # Create a property that gets the property folder
    @property
    def property_folder(self):
        return self._property_folder

    def create_property_structure(self):
        self.__create_property_folder()
        self.__create_ssl_folder()
        self.__create_trusted_certs_folder()
        # self.__create_vector_db_oidc_certs_folder()


    # Create a method that makes a list of directories in the directory path
    def __create_property_folder(self):
        # Create a directory if it does not exist
        if not os.path.exists(self._property_folder):
            os.makedirs(self._property_folder)

    def __create_trusted_certs_folder(self):
        # Create a directory if it does not exist
        if not os.path.exists(self._trusted_certs_directory_folder):
            os.makedirs(self._trusted_certs_directory_folder)

    # Create a method that creates ssl folders
    def __create_ssl_folder(self):
        # Create a directory if it does not exist
        if not os.path.exists(self._ssl_directory_folder):
            os.makedirs(self._ssl_directory_folder)
        if len(self._gather.ssl_directory_list) > 0:
            for directory in self._gather.ssl_directory_list:
                # Create a directory if it does not exist
                if not os.path.exists(os.path.join(self._ssl_directory_folder, directory)):
                    os.makedirs(os.path.join(self._ssl_directory_folder, directory))

    # def __create_vector_db_oidc_certs_folder(self):
    #     for oidc_folder in self._gather.vector_db_ssl_directory_dict.items():
    #         if not os.path.exists(os.path.join(self._ssl_directory_folder, oidc_folder)):
    #             os.makedirs(os.path.join(self._ssl_directory_folder, oidc_folder))

    def __populate_deployment_dict(self):
        try:
            # Create a copy of the deployment property file properties
            deployment_dict = copy.deepcopy(self._deployment_properties)
            deployment_dict['CAS_VERSION']['value'] = self._gather.cas_version
            deployment_dict['LICENSE']['value'] = self._gather.license_model
            deployment_dict['PLATFORM']['value'] = self._gather.platform


            return deployment_dict

        except Exception as e:
            self._logger.exception(
                "Exception from property script in __populate_deployment_dict function -  {}".format(str(e)))

    def __populate_egress_dict(self):
        try:
            # Create a copy of the deployment property file properties
            egress_dict = copy.deepcopy(self._egress_properties)
            egress_dict['GENERATE_NETWORK_POLICIES']['value'] = self._gather.np_support

            if (self._gather.np_support and self._gather.platform in ["OCP", 'ROKS']) or not self._gather.np_support:
                egress_dict.pop('K8_API_NAMESPACE')
                egress_dict.pop('K8_API_PORT')
                egress_dict.pop('K8_DNS_NAMESPACE')
                egress_dict.pop('K8_DNS_PORT')

            return egress_dict

        except Exception as e:
            self._logger.exception(
                "Exception from property script in __populate_egress_dict function -  {}".format(str(e)))

    def create_deployment_propertyfile(self):
        # Create a file
        deployment_doc = document()
        deployment_doc.add(comment("####################################################"))
        deployment_doc.add(comment("##          License, Platform and Version        ##"))
        deployment_doc.add(comment("####################################################"))

        deployment_properties = self.__populate_deployment_dict()

        for key, value in deployment_properties.items():
            self.__write_property(doc=deployment_doc,
                                  key=key,
                                  value=value['value'],
                                  note=value['comment'])

        deployment_doc.add(nl())
        deployment_doc.add(comment("####################################################"))
        deployment_doc.add(comment("##                   File Storage                 ##"))
        deployment_doc.add(comment("####################################################"))

        for key, value in self._storage_properties.items():
            self.__write_property(doc=deployment_doc,
                                  key=key,
                                  value=value['value'],
                                  note=value['comment'])


        deployment_doc.add(nl())
        deployment_doc.add(comment("####################################################"))
        deployment_doc.add(comment("##                   Egress Properties            ##"))
        deployment_doc.add(comment("####################################################"))

        egress_properties = self.__populate_egress_dict()

        for key, value in egress_properties.items():
            self.__write_property(doc=deployment_doc,
                                key=key,
                                value=value['value'],
                                note=value['comment'])

        # Create a file
        f = TOMLFile(os.path.join(self._property_folder, 'cas_deployment.toml'))
        f.write(deployment_doc)

    def create_ingress_propertyfile(self):
        # Create a file
        ingress_doc = document()
        ingress_doc.add(comment("####################################################"))
        ingress_doc.add(comment("##                 Ingress Properties             ##"))
        ingress_doc.add(comment("####################################################"))

        for key, value in self._ingress_properties.items():
            self.__write_property(doc=ingress_doc,
                                  key=key,
                                  value=value['value'],
                                  note=value['comment'])

        # Create a file
        f = TOMLFile(os.path.join(self._property_folder, 'cas_ingress.toml'))
        f.write(ingress_doc)


    # Create a method that creates a db property file
    def create_content_assistant_propertyfile(self, content_assistant_properties):
        try:
            user_doc = document()
            user_doc.add(comment("##################################################################"))
            user_doc.add(comment("##          IBM Content Assistant Properties                    ##"))
            user_doc.add(comment("##################################################################"))


            user_doc.add(nl())
            user_doc.add(comment("#########################################"))
            user_doc.add(comment("##         AI Provider Properties      ##"))
            user_doc.add(comment("#########################################"))

            # Adjust the properties for AI provider section
            for i in range(self._gather.ai_provider_number):
                if i == 0:
                    suffix = 'AI_PROVIDER'
                else:
                    suffix = f"AI_PROVIDER{i + 1}"

                watsonx_section = table()
                # loop through the db_properties dictionary
                for key, value in content_assistant_properties[suffix].items():
                    self.__write_property_table(section=watsonx_section,
                                                key=key,
                                                value=value['value'],
                                                note=value['comment'])

                user_doc.add(f"{suffix}", watsonx_section)

            user_doc.add(nl())


            f = TOMLFile(os.path.join(self._property_folder, 'cas_properties.toml'))
            f.write(user_doc)


        except Exception as e:
            self._logger.exception(
                "Exception from gather script in create_content_assistant_propertyfile function -  {}".format(str(e)))

    # Create a method that creates a db property file
    def create_vector_database_propertyfile(self, vector_database_properties):
        try:
            user_doc = document()
            user_doc.add(comment("#############################################"))
            user_doc.add(comment("##         Vector Database Properties      ##"))
            user_doc.add(comment("#############################################"))
            # Adjust the properties for AI provider section
            for vector_db in self._gather.vector_db_details:
                suffix = vector_db.get_db_label

                vector_db_section = table()
                # loop through the db_properties dictionary
                for key, value in vector_database_properties[suffix].items():
                    self.__write_property_table(section=vector_db_section,
                                                key=key,
                                                value=value['value'],
                                                note=value['comment'])

                user_doc.add(f"{suffix}", vector_db_section)
                user_doc.add(nl())


            user_doc.add(nl())
            user_doc.add(nl())

            f = TOMLFile(os.path.join(self._property_folder, 'cas_vector_database.toml'))
            f.write(user_doc)


        except Exception as e:
            self._logger.exception(
                "Exception from gather script in create_vector_database_propertyfile function -  {}".format(
                    str(e)))

    def populate_vector_database_details(self):
        try:
            # Create a copy of the CA dictionary
            vector_database_properties_dict = {}

            single_vector_database_properties_dict = {}
            for i in range(self._gather.vector_database_number):
                db_label = self._gather.vector_db_details[i].get_db_label
                ssl_enabled = self._gather.vector_db_details[i].vector_db_ssl_enabled
                for key in self._vector_database_properties.keys():
                    single_vector_database_properties_dict[key] = copy.deepcopy(self._vector_database_properties[key])

                single_vector_database_properties_dict['DATABASE_SSL_ENABLED']['value'] = ssl_enabled

                if self._gather.vector_db_details[i].get_db_auth_type == "BASICAUTH":
                    single_vector_database_properties_dict.pop('DATABASE_OIDC_ENDPOINT')
                    single_vector_database_properties_dict.pop('DATABASE_OIDC_CLIENT_ID')
                    single_vector_database_properties_dict.pop('DATABASE_OIDC_CLIENT_SECRET')
                    single_vector_database_properties_dict["DATABASE_AUTH_TYPE"]["value"] = "BASICAUTH"
                else:
                    #single_vector_database_properties_dict.pop('DATABASE_USERNAME')
                    #single_vector_database_properties_dict.pop('DATABASE_USER_PASSWORD')
                    single_vector_database_properties_dict["DATABASE_AUTH_TYPE"]["value"] = "OIDC"


                single_vector_database_properties_dict["DATABASE_LABEL"]["value"] = db_label
                vector_database_properties_dict[db_label] = copy.deepcopy(single_vector_database_properties_dict)

            return vector_database_properties_dict

        except Exception as e:
            self._logger.exception(
                "Exception from gather script in populate_vector_database_details function -  {}".format(str(e)))

    def populate_content_assistant_details(self):
        try:
            # Create a copy of the CA dictionary
            content_assistant_properties_dict = {}
            for key in self._content_assistant_properties.keys():
                content_assistant_properties_dict[key] = copy.deepcopy(self._content_assistant_properties[key])

            content_assistant_watsonx_property_dict = {}
            for key in self._content_assistant_watsonx_properties.keys():
                content_assistant_watsonx_property_dict[key] = copy.deepcopy(self._content_assistant_watsonx_properties[key])

            for i in range(self._gather.ai_provider_number):
                if i == 0:
                    content_assistant_properties_dict['AI_PROVIDER'] = copy.deepcopy(content_assistant_watsonx_property_dict)
                else:
                    content_assistant_properties_dict[f"AI_PROVIDER{i + 1}"] = copy.deepcopy(content_assistant_watsonx_property_dict)


            return content_assistant_properties_dict

        except Exception as e:
            self._logger.exception(
                "Exception from gather script in populate_content_assistant_details function -  {}".format(str(e)))

    def create_idp_propertyfile(self, idp_properties_list):
        try:

            # Create a file
            idp_doc = document()

            idp_doc.add(nl())
            idp_doc.add(comment("####################################################"))
            idp_doc.add(comment("##                  IDP Properties                ##"))
            idp_doc.add(comment("####################################################"))

            idp_section = table()

            suffix = 'IDP'
            # loop through the ldap_properties dictionary
            for key, value in idp_properties_list[0].items():
                self.__write_property_table(section=idp_section,
                                            key=key,
                                            value=value['value'],
                                            note=value['comment'])

            idp_doc.add(suffix, idp_section)

            for i in range(1, self._gather.idp_number):
                suffix = f"IDP{i + 1}"

                idp_section = table()

                idp_doc.add(nl())
                idp_doc.add(comment("####################################################"))
                idp_doc.add(comment(f"##               {suffix} Properties             ##"))
                idp_doc.add(comment("####################################################"))

                # loop through the db_properties dictionary
                for key, value in idp_properties_list[i].items():
                    self.__write_property_table(section=idp_section,
                                                key=key,
                                                value=value['value'],
                                                note=value['comment'])

                idp_doc.add(suffix, idp_section)

            f = TOMLFile(os.path.join(self._property_folder, 'cas_identity_provider.toml'))
            f.write(idp_doc)

        except Exception as e:
            self._logger.exception(
                "Exception from gather script in create_idp_propertyfile function -  {}".format(str(e)))



    # Create a private method that writes properties to a file
    @staticmethod
    def __write_property(doc, key, value, note):

        doc.add(nl())
        for i in note:
            doc.add(comment(f'{i}'))
        cred_list = ['PASSWORD', 'SECRET', 'USERNAME', 'GROUPS_NAME', 'ADMIN_USER', 'LOGIN_USER', 'CLIENT_ID', 'BIND_DN', 'USER_ID', "PASSKEY", "API_KEY"]
        if any(ele in key for ele in cred_list):
            if isinstance(value, list):
                for i in range(len(value)):
                    value[i] = string(value[i], multiline=True)
            else:
                value = string(value, multiline=True)

        doc.add(key, value)

    @staticmethod
    def __write_property_table(section, key, value, note, ):
        section.add(nl())
        for i in note:
            section.add(comment(f'{i}'))
        cred_list = ['PASSWORD', 'SECRET', 'USERNAME', 'GROUPS_NAME', 'ADMIN_USER', 'LOGIN_USER', 'BIND_DN', 'USER_ID', "NAMES" , "PASSKEY" , "API_KEY"]
        if any(ele in key for ele in cred_list):
            if isinstance(value, list):
                for i in range(len(value)):
                    value[i] = string(value[i], multiline=True)
            else:
                value = string(value, multiline=True)

        section.add(key, value)

    def populate_idp_propertyfile(self):
        try:

            idp_properties_list = []

            for i in range(self._gather.idp_number):
                idp_dict = self._gather.idp_info[i].to_dict()
                idp_prop = copy.deepcopy(self._idp_properties)

                idp_prop['PROVIDER_NAME']['value'] = idp_dict['id']
                idp_prop['DISPLAY_NAME']['value'] = "{} SSO Login".format(idp_dict['id'])


                if idp_dict['discovery_enabled']:
                    idp_prop['DISCOVERY_ENDPOINT']['value'] = idp_dict["discovery_url"]
                    idp_prop['IDP_SSL_ENABLED']['value'] = idp_dict["ssl_enabled"]
                else:
                    idp_prop.pop('DISCOVERY_ENDPOINT')

                if idp_dict['token_url']:
                    idp_prop['TOKEN_ENDPOINT']['value'] = idp_dict['token_url']

                if idp_dict["issuer"]:
                    idp_prop['ISSUER']['value'] = idp_dict["issuer"]

                if idp_dict['introspect_url'] and idp_dict['validation_method'] == "introspect":
                    idp_prop['INTROSPECT_ENDPOINT']['value'] = idp_dict['introspect_url']
                    idp_prop.pop('USERINFO_ENDPOINT')

                if idp_dict['userinfo_url'] and idp_dict['validation_method'] == "userinfo":
                    idp_prop['USERINFO_ENDPOINT']['value'] = idp_dict['userinfo_url']
                    idp_prop.pop('INTROSPECT_ENDPOINT')

                if idp_dict['revoke_url']:
                    idp_prop['REVOCATION_ENDPOINT']['value'] = idp_dict['revoke_url']
                else:
                    idp_prop.pop('REVOCATION_ENDPOINT')

                if idp_dict['jwks_url']:
                    idp_prop['JWKS_ENDPOINT']['value'] = idp_dict['jwks_url']

                idp_prop['VALIDATION_METHOD']['value'] = idp_dict['validation_method']
                idp_prop['USER_IDENTIFIER']['value'] = idp_dict['user_identifier']
                idp_prop['UNIQUE_USER_IDENTIFIER']['value'] = idp_dict['unique_user_identifier']
                idp_prop['USER_IDENTIFIER_TO_CREATE_SUBJECT']['value'] = idp_dict['user_identifier_to_sub']

                idp_properties_list.append(idp_prop)

            return idp_properties_list


        except Exception as e:
            self._logger.exception(
                "Exception from gather script in create_ldap_propertyfile function -  {}".format(str(e)))

