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

# Create a class to silently set variables from config file
#  - the class should have a constructor that takes the filename as an argument
#  - the class should have a method to parse the file

import os

import toml
import typer

from ..gather.gather_prerequisites import GatherPrereqOptions
from ..utilities.prerequisites_utilites import gather_var


# create a class to silently set variables from config file
class SilentGatherPrereqOptions(GatherPrereqOptions):
    # Default path for env file
    _envfile_path = os.path.join(os.getcwd(), "silent_config",
                                 "silent_install_prerequisites.toml")
    _error_list = []

    def __init__(self, logger, envfile_path=_envfile_path):

        super().__init__(logger, console=None)

        self._envfile_path = envfile_path

        try:
            self._envfile = toml.loads(open(self._envfile_path, encoding="utf-8").read())
        except Exception as e:
            self._logger.exception(
                f"Exception from silent.py script - error loading {self._envfile_path} file -  {str(e)}")

    def error_check(self):
        if len(self._error_list) > 0:
            for error in self._error_list:
                self._logger.warning(error)

            raise typer.Exit(code=1)
        return len(self._error_list)

    def silent_platform(self):
        platform = gather_var(key="PLATFORM", valid_values=[1, 2], _logger=self._logger, _envfile=self._envfile,
                              _error_list=self._error_list)
        if platform is not None:
            self.platform = self.Platform(platform).name
            if self.platform == 'other' and gather_var(key="INGRESS", _logger=self._logger, _envfile=self._envfile,
                                                       _error_list=self._error_list) is not None:
                self.ingress = gather_var(key="INGRESS", _logger=self._logger, _envfile=self._envfile,
                                          _error_list=self._error_list)

    def silent_version(self, version_data):
        version = version_data.get("VERSION", '1.0.0')
        if version:
            self._cas_version = version

    def silent_network_policies_support(self):
        np_support = gather_var(key="GENERATE_NETWORK_POLICIES", _logger=self._logger, _envfile=self._envfile,
                                    _error_list=self._error_list)
        if np_support is not None:
            self._np_support = np_support
        else:
            self._np_support = False


    def silent_idp(self):
        self._idp_number = self.__find_idp_count()
        for i in range(self._idp_number):
            idp_id = f"IDP{str(i + 1) if i > 0 else ''}"
            idp_discovery_enabled = gather_var(key="DISCOVERY_ENABLED", section_header=idp_id, _logger=self._logger,
                                               _envfile=self._envfile, _error_list=self._error_list)
            if idp_discovery_enabled:
                idp_discovery_url = gather_var(key="DISCOVERY_URL", section_header=idp_id, valid_values="url",
                                               _logger=self._logger, _envfile=self._envfile,
                                               _error_list=self._error_list)
            else:
                idp_discovery_url = None

            if idp_discovery_enabled is not None:
                idp = self.Idp(idp_discovery_enabled, idp_id, idp_discovery_url)
                idp.parse_discovery_url()
                self._idp_info.append(idp)

    def silent_vector_db(self):
        self._vector_database_number = self.__find_vectordb_count()
        for i in range(self._vector_database_number):
            db_label = f"VECTORDB{str(i + 1) if i > 0 else ''}"

            auth_value = gather_var(key="DATABASE_AUTH_TYPE", section_header=db_label, valid_values=[1, 2], _logger=self._logger, _envfile=self._envfile, _error_list=self._error_list)
            auth_type = self.AuthType(auth_value).name

            ssl_enabled = gather_var(key="DATABASE_SSL_ENABLE", section_header=db_label, _logger=self._logger, _envfile=self._envfile,
                                     _error_list=self._error_list)

            vector_db_instance = self.VectorDatabase(vector_db_label=db_label, vector_db_auth_type=auth_type, ssl_enabled=ssl_enabled)

            if ssl_enabled:
                self._ssl_directory_list.append(f"{db_label.lower()}")
                if auth_type.lower() == "oidc":
                    self._ssl_directory_list.append(f"{db_label.lower()}-oidc")

            self._vector_database_details.append(vector_db_instance)

    def silent_ai_provider_count(self):
        self._ai_provider_number = gather_var(key="AI_PROVIDER_COUNT",valid_values=(1, float('inf')), _logger=self._logger,
                               _envfile=self._envfile, _error_list=self._error_list)

    def silent_license_model(self):
        license_model = gather_var(key="LICENSE", valid_values=["FNCM", "CP4BA"], _logger=self._logger,
                                   _envfile=self._envfile, _error_list=self._error_list)
        if license_model is not None:
            self._license_model = license_model

    # Function to read namespace information from toml file
    def silent_namespace(self):
        namespace = self._envfile.get("NAMESPACE")
        super().collect_namespace(namespace)
        self._namespace = super().namespace

    def __find_idp_count(self):
        num_idp = 0
        for key in self._envfile:
            # Parse the keys with more than 4 characters ie. IDP2; IDP3
            if "IDP" in key:
                num_idp += 1
        return num_idp

    def __find_vectordb_count(self):
        vectordb_count = 0
        for key in self._envfile:
            # Parse the keys with more than 4 characters ie. IDP2; IDP3
            if "VECTORDB" in key:
                vectordb_count += 1
        return vectordb_count


