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

import os


class GenerateConfigMaps:
    """Generates Kubernetes ConfigMap manifests for IBM Content Assistant."""

    def __init__(self, namespace, logger=None):
        self._logger = logger
        self._generate_folder = os.path.join(os.getcwd(), "generatedFiles", namespace)
        self._generate_configmaps_folder = os.path.join(self._generate_folder, "configmaps")

    def __create_configmaps_folder(self):
        if not os.path.exists(self._generate_configmaps_folder):
            os.makedirs(self._generate_configmaps_folder)

    def create_modelgateway_configmap(self, prefix: str, use_ssl: bool, ca_certs_secret_name: str, gateway_url: str):
        """
        Creates a Kubernetes ConfigMap for the ModelGateway AI provider.

        All configmap key names and the configmap/file names are derived from
        ``prefix`` (the TOML section name, e.g. ``MODELGATEWAY``), so the
        output automatically reflects whatever section name is in the property file.

        Writes generatedFiles/<namespace>/configmaps/ibm-content-assistant-<prefix_lower>-configmap.yaml
        """
        self.__create_configmaps_folder()

        configmap_name = "ibm-content-assistant-config"
        configmap_filename = "ibm-content-assistant-configmap.yaml"
        configmap_filepath = os.path.join(self._generate_configmaps_folder, configmap_filename)

        use_ssl_str = "true" if use_ssl else "false"

        content = (
            "apiVersion: v1\n"
            "kind: ConfigMap\n"
            "metadata:\n"
            f"  name: {configmap_name}\n"
            "data:\n"
            f"  MODEL_GATEWAY_USE_SSL: \"{use_ssl_str}\"\n"
            f"  MODEL_GATEWAY_CA_CERTS_SECRET_NAME: \"{ca_certs_secret_name}\"\n"
            f"  MODEL_GATEWAY_URL: \"{gateway_url}\"\n"
        )

        with open(configmap_filepath, "w+") as f:
            f.write(content)

        self._logger.info(f"Created ModelGateway ConfigMap: {configmap_name}")
