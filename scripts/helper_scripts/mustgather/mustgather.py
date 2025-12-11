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
from pathlib import Path

from rich import print
from rich.panel import Panel
from rich.text import Text

from ..utilities.prerequisites_utilites import write_yaml_to_file, write_log_to_file


# Create a MustGather Class

class MustGather:

    def __init__(self, console, namespace, logger=None, mustgather_folder="", deployment_details=dict, operator_details={}, kube=None):
        self._logger = logger
        self._console = console
        self._deployment_details = deployment_details
        self._operator_details = operator_details
        self._kube = kube
        self._mustgather_folder = mustgather_folder
        self._namespace = namespace
        self._version = "1.0.0"
        self._cr_name = ""
        if "name" in self._deployment_details.keys():
            self._cr_name = deployment_details["name"]
        if "version" in deployment_details.keys():
            self._version = deployment_details["version"]
        elif "release" in operator_details.keys():
            self._version = operator_details["release"]

    def to_dict(self):
        return {
            "deployment_details": self._deployment_details,
            "operator_details": self._operator_details,
            "mustgather_folder": self._mustgather_folder,
            "namespace": self._namespace,
            "cr_name": self._cr_name
        }

    def collect_cluster_info(self, progress):
        # Number of tasks = 4

        # Create folder for secrets if it does not exist
        cluster_folder_path = os.path.join(self._mustgather_folder, "cluster")
        if not os.path.exists(cluster_folder_path):
            os.makedirs(cluster_folder_path)
        try:

            progress.log(Panel.fit("Starting Cluster Information Collection", style="cyan"))
            progress.log()
            progress.log(f"Collecting cluster version information")
            progress.log()
            path = os.path.join(
                f"{cluster_folder_path}",
                "cluster_version.yaml",
            )
            if os.path.isfile(path):
                self._logger.info("Log already collected in the previous step. Skipping...")
            else:
                version_response = self._kube.get_version()
                write_yaml_to_file(version_response, path)
        except Exception as e:
            self._logger.info("Unable to retrieve version information, caught %s Skipping...", e)
            progress.log(Text(f"Unable to retrieve version information", style="bold red"))
            progress.log()

        try:
            progress.log("Collecting cluster events")
            progress.log()
            path = os.path.join(
                f"{cluster_folder_path}",
                "events.yaml",
            )
            if os.path.isfile(path):
                self._logger.info("Log already collected in the previous step. Skipping...")
            else:
                version_response = self._kube.get_events(self._namespace)
                write_yaml_to_file(version_response, path)


        except Exception as e:
            self._logger.info("Unable to retrieve events, caught %s Skipping...", e)
            progress.log(Text(f"Unable to retrieve events", style="bold red"))
            progress.log()

        try:
            progress.log("Collecting cluster node information")
            progress.log()
            path = os.path.join(
                f"{cluster_folder_path}",
                "nodes.yaml",
            )
            if os.path.isfile(path):
                self._logger.info("Log already collected in the previous step. Skipping...")
            else:
                nodes = self._kube.get_nodes()
                write_yaml_to_file(nodes, path)

        except Exception as e:
            self._logger.info("Unable to retrieve nodes, caught %s Skipping...", e)
            progress.log(Text(f"Unable to retrieve nodes", style="bold red"))
            progress.log()

        try:
            progress.log("Collecting node resource allocations and usage")
            progress.log()
            path = os.path.join(
                f"{cluster_folder_path}",
                "nodeusage.yaml",
            )
            if os.path.isfile(path):
                self._logger.info("Log already collected in the previous step. Skipping...")
            else:
                node = self._kube.get_node_top()
                write_yaml_to_file(node, path)

        except Exception as e:
            self._logger.info("Unable to retrieve node usage information, caught %s Skipping...", e)
            progress.log(Text(f"Unable to retrieve node usage information, {e}", style="bold red"))

        progress.log(Panel.fit("Cluster Information Collection Completed", style="bold green"))

    # Function to collect secrets information
    def collect_secret_info(self, progress, secrets=[]):

        # Create folder for secrets if it does not exist
        secrets_folder_path = os.path.join(self._mustgather_folder, "secrets")
        if not os.path.exists(secrets_folder_path):
            os.makedirs(secrets_folder_path)

        try:
            progress.log(Panel.fit("Starting Secrets Information Collection", style="cyan"))
            progress.log()

            for secret in secrets:
                progress.log(f"Collecting secret {secret}")
                progress.log()
                path = os.path.join(
                    f"{secrets_folder_path}",
                    f"{secret}.yaml",
                )
                if os.path.isfile(path):
                    self._logger.info("Log already collected in the previous step. Skipping...")
                else:
                    secret_response = self._kube.describe_secret(secret, self._namespace, progress)
                    write_yaml_to_file(secret_response, path)

            progress.log()
            progress.log(Panel.fit("Secrets Information Collection Completed", style="bold green"))

        except Exception as e:
            self._logger.info("Unable to retrieve secrets, caught %s Skipping...", e)
            progress.log(Text(f"Unable to retrieve secrets", style="bold red"))
            progress.log()

    # Function to collect configmap information
    def collect_configmap_info(self, progress, configmaps=[]):

        # Create folder for configmaps if it does not exist
        configmap_folder_path = os.path.join(self._mustgather_folder, "configmaps")
        if not os.path.exists(configmap_folder_path):
            os.makedirs(configmap_folder_path)

        try:
            progress.log(Panel.fit("Starting ConfigMap Information Collection", style="cyan"))
            progress.log()

            for configmap in configmaps:
                progress.log(f"Collecting configmap {configmap}")
                progress.log()
                path = os.path.join(
                    f"{configmap_folder_path}",
                    f"{configmap}.yaml",
                )
                if os.path.isfile(path):
                    self._logger.info("Log already collected in the previous step. Skipping...")
                else:
                    configmap_response = self._kube.describe_configmap(configmap, self._namespace)
                    write_yaml_to_file(configmap_response, path)

            progress.log()
            progress.log(Panel.fit("ConfigMap Information Collection Completed", style="bold green"))

        except Exception as e:
            self._logger.info("Unable to retrieve configmaps, caught %s Skipping...", e)
            progress.log(Text(f"Unable to retrieve configmaps", style="bold red"))
            progress.log()

    # Function to collection deployment information
    def collect_deployment_info(self, progress, deployments=list):

        # Create folder for deployments if it does not exist
        deployment_folder_path = os.path.join(self._mustgather_folder, "deployments")
        if not os.path.exists(deployment_folder_path):
            os.makedirs(deployment_folder_path)

        try:
            progress.log(Panel.fit("Starting Deployment Information Collection", style="cyan"))
            progress.log()

            for deployment in deployments:
                progress.log(f"Collecting deployment {deployment}")
                progress.log()
                path = os.path.join(
                    f"{deployment_folder_path}",
                    f"{deployment}.yaml",
                )
                if os.path.isfile(path):
                    self._logger.info("Log already collected in the previous step. Skipping...")
                else:
                    deployment_response = self._kube.describe_deployment(deployment, self._namespace)
                    write_yaml_to_file(deployment_response, path)

            progress.log()
            progress.log(Panel.fit("Deployment Information Collection Completed", style="bold green"))

        except Exception as e:
            self._logger.info("Unable to retrieve deployments, caught %s Skipping...", e)
            progress.log(Text(f"Unable to retrieve deployments: {e}", style="bold red"))
            progress.log()

    # Function to collect ingress information
    def collect_ingress_info(self, progress, ingresses=[]):

        # Create folder for ingresses if it does not exist
        ingress_folder_path = os.path.join(self._mustgather_folder, "ingresses")
        if not os.path.exists(ingress_folder_path):
            os.makedirs(ingress_folder_path)

        try:
            progress.log(Panel.fit("Starting Ingress Information Collection", style="cyan"))
            progress.log()

            for ingress in ingresses:
                progress.log(f"Collecting ingress {ingress}")
                progress.log()
                path = os.path.join(
                    f"{ingress_folder_path}",
                    f"{ingress}.yaml",
                )
                if os.path.isfile(path):
                    self._logger.info("Log already collected in the previous step. Skipping...")
                else:
                    ingress_response = self._kube.describe_ingress(ingress, self._namespace)
                    write_yaml_to_file(ingress_response, path)

            progress.log()
            progress.log(Panel.fit("Ingress Information Collection Completed", style="bold green"))

        except Exception as e:
            self._logger.info("Unable to retrieve ingresses, caught %s Skipping...", e)
            progress.log(Text(f"Unable to retrieve ingresses", style="bold red"))
            progress.log()

    # Function to collect route or ingress information
    def collect_route_info(self, progress, routes=[]):

        # Create folder for routes if it does not exist
        route_folder_path = os.path.join(self._mustgather_folder, "routes")
        if not os.path.exists(route_folder_path):
            os.makedirs(route_folder_path)

        try:
            progress.log(Panel.fit("Starting Route Information Collection", style="cyan"))
            progress.log()

            for route in routes:
                progress.log(f"Collecting route {route}")
                progress.log()
                path = os.path.join(
                    f"{route_folder_path}",
                    f"{route}.yaml",
                )
                if os.path.isfile(path):
                    self._logger.info("Log already collected in the previous step. Skipping...")
                else:
                    route_response = self._kube.describe_route(route, self._namespace)
                    write_yaml_to_file(route_response, path)

            progress.log()
            progress.log(Panel.fit("Route Information Collection Completed", style="bold green"))

        except Exception as e:
            self._logger.info("Unable to retrieve routes, caught %s Skipping...", e)
            progress.log(Text(f"Unable to retrieve routes", style="bold red"))
            progress.log()


    # Function to collect all HorizonalPodAutoscaler information
    def collect_hpa_info(self, progress, hpas=[]):
        # Create folder for hpas if it does not exist
        hpa_folder_path = os.path.join(self._mustgather_folder, "hpas")
        if not os.path.exists(hpa_folder_path):
            os.makedirs(hpa_folder_path)

        try:
            progress.log(Panel.fit("Starting HPA Information Collection", style="cyan"))
            progress.log()

            for hpa in hpas:
                progress.log(f"Collecting HPA {hpa}")
                progress.log()
                path = os.path.join(
                    f"{hpa_folder_path}",
                    f"{hpa}.yaml",
                )
                if os.path.isfile(path):
                    self._logger.info("Log already collected in the previous step. Skipping...")
                else:
                    hpa_response = self._kube.describe_hpa(hpa, self._namespace)
                    write_yaml_to_file(hpa_response, path)

            progress.log()
            progress.log(Panel.fit("HPA Information Collection Completed", style="bold green"))

        except Exception as e:
            self._logger.info("Unable to retrieve HPAs, caught %s Skipping...", e)
            progress.log(Text(f"Unable to retrieve HPAs", style="bold red"))
            progress.log()

    # Function to collect Network Policy information
    def collect_network_policy_info(self, progress, network_policies=[]):

        # Create folder for network policies if it does not exist
        network_policy_folder_path = os.path.join(self._mustgather_folder, "network_policies")
        if not os.path.exists(network_policy_folder_path):
            os.makedirs(network_policy_folder_path)

        try:
            progress.log(Panel.fit("Starting Network Policy Information Collection", style="cyan"))
            progress.log()

            for network_policy in network_policies:
                progress.log(f"Collecting network policy {network_policy}")
                progress.log()
                path = os.path.join(
                    f"{network_policy_folder_path}",
                    f"{network_policy}.yaml",
                )
                if os.path.isfile(path):
                    self._logger.info("Log already collected in the previous step. Skipping...")
                else:
                    network_policy_response = self._kube.describe_network_policy(network_policy, self._namespace)
                    write_yaml_to_file(network_policy_response, path)

            progress.log()
            progress.log(Panel.fit("Network Policy Information Collection Completed", style="bold green"))

        except Exception as e:
            self._logger.info("Unable to retrieve network policies, caught %s Skipping...", e)
            progress.log(Text(f"Unable to retrieve network policies", style="bold red"))
            progress.log()

    # Function to collect service information
    def collect_service_info(self, progress, services=[]):

        # Create folder for services if it does not exist
        service_folder_path = os.path.join(self._mustgather_folder, "services")
        if not os.path.exists(service_folder_path):
            os.makedirs(service_folder_path)

        try:
            progress.log(Panel.fit("Starting Service Information Collection", style="cyan"))
            progress.log()

            for service in services:
                progress.log(f"Collecting service {service}")
                progress.log()
                path = os.path.join(
                    f"{service_folder_path}",
                    f"{service}.yaml",
                )
                if os.path.isfile(path):
                    self._logger.info("Log already collected in the previous step. Skipping...")
                else:
                    service_response = self._kube.describe_service(service, self._namespace)
                    write_yaml_to_file(service_response, path)

            progress.log()
            progress.log(Panel.fit("Service Information Collection Completed", style="bold green"))

        except Exception as e:
            self._logger.info("Unable to retrieve services, caught %s Skipping...", e)
            progress.log(Text(f"Unable to retrieve services", style="bold red"))
            progress.log()

    # Function to collect pvcs
    def collect_pvc_info(self, progress, pvcs=list):

        # Create folder for pvcs if it does not exist
        pvc_folder_path = os.path.join(self._mustgather_folder, "pvcs")
        if not os.path.exists(pvc_folder_path):
            os.makedirs(pvc_folder_path)

        try:
            progress.log(Panel.fit("Starting PVC Information Collection", style="cyan"))
            progress.log()

            for pvc in pvcs:
                progress.log(f"Collecting PVC {pvc}")
                progress.log()
                path = os.path.join(
                    f"{pvc_folder_path}",
                    f"{pvc}.yaml",
                )
                if os.path.isfile(path):
                    self._logger.info("Log already collected in the previous step. Skipping...")
                else:
                    pvc_response = self._kube.describe_pvc(pvc, self._namespace)
                    write_yaml_to_file(pvc_response, path)

            progress.log()
            progress.log(Panel.fit("PVC Information Collection Completed", style="bold green"))

        except Exception as e:
            self._logger.info("Unable to retrieve pvcs, caught %s Skipping...", e)
            progress.log(Text(f"Unable to retrieve pvcs", style="bold red"))
            progress.log()

    # Function to write CR file
    def write_cr_file(self, progress, name):
        try:
            progress.log(Panel.fit("Collecting IBM Content Assistant Custom Resource File", style="cyan"))
            progress.log()
            path = os.path.join(
                f"{self._mustgather_folder}",
                f"{self._cr_name}-cr.yaml",
            )
            if os.path.isfile(path):
                self._logger.info("Log already collected in the previous step. Skipping...")
            else:
                cr_response = self._kube.custom_resource

                progress.log(f"Collecting custom resource {name}")
                write_yaml_to_file(cr_response, path)
            progress.log()
            progress.log(Panel.fit("IBM Content Assistant Custom Resource Collection Completed", style="bold green"))

        except Exception as e:
            self._logger.info("Unable to retrieve CR, caught %s Skipping...", e)
            progress.log(Text(f"Unable to retrieve CR", style="bold red"))
            progress.log()

    # Function to collect storage class information
    def collect_storage_class_info(self, progress, storage_classes=[]):

        # Create folder for storage if it does not exist
        storageclass_folder_path = os.path.join(self._mustgather_folder, "storageclasses")
        if not os.path.exists(storageclass_folder_path):
            os.makedirs(storageclass_folder_path)

        try:
            progress.log(Panel.fit("Starting Storage Class Information Collection", style="cyan"))
            progress.log()

            for storage_class in storage_classes:
                progress.log(f"Collecting storage class {storage_class}")
                progress.log()
                path = os.path.join(
                    f"{storageclass_folder_path}",
                    f"{storage_class}.yaml",
                )
                if os.path.isfile(path):
                    self._logger.info("Log already collected in the previous step. Skipping...")
                else:
                    storage_class_response = self._kube.describe_storage_class(storage_class)
                    write_yaml_to_file(storage_class_response, path)

            progress.log()
            progress.log(Panel.fit("Storage Class Information Collection Completed", style="bold green"))

        except Exception as e:
            self._logger.info("Unable to retrieve storage classes, caught %s Skipping...", e)
            progress.log(Text(f"Unable to retrieve storage classes", style="bold red"))
            progress.log()

    def collect_network_policy_templates(self,progress, operator_details):
        policies_folder_path = os.path.join(self._mustgather_folder, "templates")
        if not os.path.exists(policies_folder_path):
            os.makedirs(policies_folder_path)
            progress.log()
            progress.log("Creating Network Policy Templates folder")
        else:
            progress.log()
            progress.log("Using existing Network Policy Templates folder")

        operator_pods = operator_details["pods"]
        try:
            if len(operator_pods) == 0:
                progress.log()
                progress.log(Text(f"No Operator pods found", style="bold red"))
                return
            progress.log()
            progress.log("Collecting Egress Network Policy Templates")
            progress.log()
            progress.log("Collecting Ingress Network Policy Templates")

            copied = self._kube.copy_files_from_pod(pod_name=operator_pods[0], namespace=self._namespace, src_path=f"/tmp/{self._namespace}/network-policies", dest_path=policies_folder_path)

            if not copied:
                progress.log(Text(f"Network Policy Templates not found in Operator", style="bold red"))
                progress.log()
                progress.log(Text(f"Make sure shared_configuration.sc_generate_sample_network_policies: true is present in CR\n"
                                  f"If the parameter is enabled in CR, wait for a reconcile for the operator to generate the templates", style="bold red"))
                return

            progress.log()
            progress.log(Panel.fit("Network Policy Templates Collection Completed", style="bold green"))
        except Exception as e:
            self._logger.info("Unable to retrieve Network Policy Templates, caught %s Skipping...", e)
            progress.log()
            progress.log(Text(f"Network Policy from Templates not found in Operator\n\n"
                              f"Make sure shared_configuration.sc_generate_sample_network_policies: true is present in CR\n"
                              f"If the parameter is enabled in CR, wait for a reconcile for the operator to generate the templates", style="bold red"))
            progress.log()
    
    def auto_apply_networkpolicy(self):
        # Create network policy folder path
        policies_folder_path = os.path.join(self._mustgather_folder, "templates", 'cas')

        egress_folder_path = os.path.join(policies_folder_path, "egress")
        ingress_folder_path = os.path.join(policies_folder_path, "ingress")

        # Collect all file names from the egress and ingress folders
        egress_files = list(Path(egress_folder_path).glob("*.yaml")) if os.path.exists(egress_folder_path) else []
        ingress_files = list(Path(ingress_folder_path).glob("*.yaml")) if os.path.exists(ingress_folder_path) else []

        if len(egress_files) == 0:
            self._logger.info(f"No egress network policy files found in CASNetworkPolicies/")
            print()
            print(Panel.fit(Text(f"No egress network policy files found in CASNetworkPolicies/templates/cas/egress/", style="bold red")))
        if len(ingress_files) == 0:
            self._logger.info(f"No ingress network policy files found in CASNetworkPolicies/")
            print()
            print(Panel.fit(Text(f"No ingress network policy files found in CASNetworkPolicies/templates/cas/ingress/", style="bold red")))
        if len(egress_files) == 0 and len(ingress_files) == 0:
            return

         # Apply each network policy file

        print()
        print(Panel.fit(Text(f"Applying Egress and Ingress Network Policies"), style="cyan"))

        for file in egress_files:
            # Get Filename from path
            file_name = os.path.basename(file)
            self._logger.info(f"Applying network policy file: {str(file)}")
            try:
                applied = self._kube.apply_cluster_resource_files(resource_type='network_policy', resource_file=str(file), namespace=self._namespace)
                if not applied:
                    self._logger.info(f"Failed to apply network policy file: {str(file_name)}")
                    print()
                    print(Text(f"Failed to apply network policy file: {str(file_name)}", style="bold red"))
                else:
                    self._logger.info(f"Successfully applied network policy file: {str(file_name)}")
                    print()
                    print(Text(f"Successfully applied network policy file: {str(file_name)}", style="bold green"))
            except Exception as e:
                self._logger.info(f"Failed to apply network policy file {str(file_name)}: {e}")
                continue


        for file in ingress_files :
            # Get Filename from path
            file_name = os.path.basename(file)
            self._logger.info(f"Applying network policy file: {str(file)}")
            try:
                applied = self._kube.apply_cluster_resource_files(resource_type='network_policy', resource_file=str(file), namespace=self._namespace)
                if not applied:
                    self._logger.info(f"Failed to apply network policy file: {str(file_name)}")
                    print()
                    print(Text(f"Failed to apply network policy file: {str(file_name)}", style="bold red"))
                else:
                    self._logger.info(f"Successfully applied network policy file: {str(file_name)}")
                    print()
                    print(Text(f"Successfully applied network policy file: {str(file_name)}", style="bold green"))
            except Exception as e:
                self._logger.info(f"Failed to apply network policy file {str(file_name)}: {e}")
                continue

        print()
        print(Panel.fit(Text(f"Successfully applied Egress and Ingress Network Policies", style="bold green")))


    # Function to collect general pod information
    def collect_pod_info(self, progress, pod_path, pod, init_containers=list, component="", container_name=""):

        # Collect product version
        self.get_component_version(pod, pod_path, progress)

        # Collect Python Packages
        if component not in ["operator"]:
            self.get_python_packages(pod, pod_path, progress)

        # Collect Python Version
        if component not in ["operator"]:
            self.get_python_version(pod, pod_path, progress)

        # Collect Environment Variables
        if component not in ["operator"]:
            self.get_environment_variables(pod, pod_path, progress)

        # Collect Pod Metrics
        progress.log(f"Collecting pod metrics")
        progress.log()
        path = os.path.join(
            f"{pod_path}",
            f"metrics.yaml",
        )
        pod_metrics_response = self._kube.get_pod_metrics(pod, self._namespace)
        write_yaml_to_file(pod_metrics_response, path)

        # Collect pod events
        progress.log(f"Collecting pod events")
        progress.log()
        path = os.path.join(
            f"{pod_path}",
            f"events.yaml",
        )

        pod_events_response = self._kube.get_pod_events(pod, self._namespace)
        write_yaml_to_file(pod_events_response, path)

        # Collect init-container logs
        for container in init_containers:
            progress.log(f"Collecting init-container logs: {container}")
            progress.log()
            path = os.path.join(
                f"{pod_path}",
                f"{container}.log",
            )

            init_container_response = self._kube.get_init_container_logs(pod, self._namespace, container)
            write_log_to_file(init_container_response, path)

        # Collect pod yaml
        path = os.path.join(
            f"{pod_path}",
            f"{pod}.yaml",
        )

        pod_response = self._kube.describe_pod(pod, self._namespace)
        write_yaml_to_file(pod_response, path)

    # Function to collect GenAI_Connector Information
    def collect_genai_connector_info(self, progress, collect_sensitive, pods=list, init_containers=list):

        # Create folder for GenAI_Connector if it does not exist
        genai_connector_folder_path = os.path.join(self._mustgather_folder, "genai_connector")
        if not os.path.exists(genai_connector_folder_path):
            os.makedirs(genai_connector_folder_path)

        genai_connector_pods = pods

        progress.log(Panel.fit("Starting GenAI Connector Information Collection", style="cyan"))
        progress.log()

        try:
            if len(genai_connector_pods) == 0:
                progress.log(Text(f"No GenAI Connector pods found", style="bold red"))
                progress.log()
                return

            for pod in genai_connector_pods:
                pod_path = os.path.join(f"{genai_connector_folder_path}", "pods", pod)
                if not os.path.exists(pod_path):
                    os.makedirs(pod_path)

                progress.log(Panel.fit(f"Collecting for GenAI Connector pod: {pod}", style="yellow"))
                progress.log()

                self.collect_pod_info(progress, pod_path, pod, init_containers, "genai_connector", container_name="ibm-content-assistant-deployment")

                # Collect GenAI Connector Logs


                progress.log(f"Collecting container logs")
                progress.log()
                path = os.path.join(
                    f"{pod_path}",
                    f"genai-connector.log",
                )
                container_response = self._kube.get_container_logs(pod, self._namespace, container="ibm-content-assistant-deployment")
                write_log_to_file(container_response, path)



            progress.log(Panel.fit("GenAI Connector Information Collection Completed", style="bold green"))
            progress.log()

        except Exception as e:
            self._logger.info("Unable to retrieve GenAI Connector, caught %s Skipping...", e)
            progress.log(Text(f"Unable to retrieve GenAI Connector Logs", style="bold red"))
            progress.log()

    # Collect RBAC Information
    def collect_rbac_info(self, progress, operator_details=dict):
        # Create folder for RBAC if it does not exist
        rbac_folder_path = os.path.join(self._mustgather_folder, "rbac")
        if not os.path.exists(rbac_folder_path):
            os.makedirs(rbac_folder_path)

        progress.log(Panel.fit("Starting RBAC Information Collection", style="cyan"))
        progress.log()

        try:
            # Collect Role Information
            role = operator_details["role"]
            progress.log(f"Collecting role {role}")
            progress.log()
            path = os.path.join(
                f"{rbac_folder_path}",
                f"role.yaml",
            )
            if os.path.isfile(path):
                self._logger.info("Log already collected in the previous step. Skipping...")
            else:
                role_response = self._kube.describe_role(role, self._namespace)
                if role_response is None or not role_response:
                    progress.log(Text(f"Role {role} not found", style="bold red"))
                    progress.log()
                    self._logger.info(f"Role {role} not found in namespace {self._namespace}. Skipping...")
                else:
                    write_yaml_to_file(role_response, path)

            # Collect RoleBinding Information
            role_binding = operator_details["rolebinding"]
            progress.log(f"Collecting role binding {role_binding}")
            progress.log()
            path = os.path.join(
                f"{rbac_folder_path}",
                f"role_binding.yaml",
            )
            if os.path.isfile(path):
                self._logger.info("Log already collected in the previous step. Skipping...")
            else:
                role_binding_response = self._kube.describe_role_binding(role_binding, self._namespace)
                if role_binding_response is None or not role_binding_response:
                    progress.log(Text(f"RoleBinding {role_binding} not found", style="bold red"))
                    progress.log()
                    self._logger.info(f"RoleBinding {role_binding} not found in namespace {self._namespace}. Skipping...")
                else:
                    write_yaml_to_file(role_binding_response, path)


            # Collect ServiceAccount Information
            service_account = operator_details["service_account"]
            progress.log(f"Collecting service account {service_account}")
            progress.log()
            path = os.path.join(
                f"{rbac_folder_path}",
                f"service_account.yaml",
            )
            if os.path.isfile(path):
                self._logger.info("Log already collected in the previous step. Skipping...")
            else:
                service_account_response = self._kube.describe_service_account(service_account, self._namespace)

                if service_account_response is None or not service_account_response:
                    progress.log(Text(f"ServiceAccount {service_account} not found", style="bold red"))
                    progress.log()
                    self._logger.info(f"ServiceAccount {service_account} not found in namespace {self._namespace}. Skipping...")
                else:
                    write_yaml_to_file(service_account_response, path)

            progress.log(Panel.fit("RBAC Information Collection Completed", style="bold green"))
            progress.log()

        except Exception as e:
            self._logger.info("Unable to retrieve RBAC information, caught %s Skipping...", e)
            progress.log(Text(f"Unable to retrieve RBAC information", style="bold red"))
            progress.log()



    # Function to collect Content Operator information
    def collect_operator_info(self, progress, collect_sensitive, operator_details=dict):

        # Create folder for Content Operator if it does not exist
        operator_folder_path = os.path.join(self._mustgather_folder, "operator")
        if not os.path.exists(operator_folder_path):
            os.makedirs(operator_folder_path)

        operator_pods = operator_details["pods"]

        progress.log(Panel.fit("Starting IBM Content Assistant Operator Information Collection", style="cyan"))
        progress.log()

        try:
            # Collect Deployment Information
            deployment = operator_details["deployment"]
            progress.log(f"Collecting deployment {deployment}")
            progress.log()
            path = os.path.join(
                f"{operator_folder_path}",
                f"{deployment}.yaml",
            )

            deployment_response = self._kube.describe_deployment(deployment, self._namespace)
            write_yaml_to_file(deployment_response, path)

            deployment_type = operator_details["type"]

            if deployment_type == "OLM":

                # Collect CSV Information
                csv = operator_details["installedCSV"]
                progress.log(f"Collecting CSV {csv}")
                progress.log()
                path = os.path.join(
                    f"{operator_folder_path}",
                    f"cluster-service-version.yaml",
                )

                csv_response = self._kube.describe_csv(csv, self._namespace)
                write_yaml_to_file(csv_response, path)


                # Collect Subscription Information
                subscription = operator_details["subscription"]
                progress.log(f"Collecting subscription {subscription}")
                progress.log()
                path = os.path.join(
                    f"{operator_folder_path}",
                    f"subscription.yaml",
                )

                subscription_response = self._kube.describe_subscription(subscription, self._namespace)
                write_yaml_to_file(subscription_response, path)

                # Collect CatalogSource Information

                catalogsource = operator_details["catalogSource"]
                catalogsource_namespace = operator_details["sourceNamespace"]
                progress.log(f"Collecting catalogsource {catalogsource}")
                progress.log()
                path = os.path.join(
                    f"{operator_folder_path}",
                    f"catalogsource.yaml",
                )

                catalogsource_response = self._kube.describe_catalogsource(catalogsource, catalogsource_namespace)
                write_yaml_to_file(catalogsource_response, path)

                # Collect OperatorGroup Information
                operator_group = operator_details["operatorGroup"]
                progress.log(f"Collecting operator group {operator_group}")
                progress.log()
                path = os.path.join(
                    f"{operator_folder_path}",
                    f"operatorgroup.yaml",
                )

                operator_group_response = self._kube.describe_operator_group(operator_group, self._namespace)
                write_yaml_to_file(operator_group_response, path)

            # Collect Configuration Files
            if len(operator_pods) == 0:
                progress.log(Text(f"No Content Operator pods found", style="bold red"))
                progress.log()
                return

            for pod in operator_pods:

                pod_path = os.path.join(f"{operator_folder_path}", "pods", pod)
                if not os.path.exists(pod_path):
                    os.makedirs(pod_path)

                progress.log(Panel.fit(f"Collecting for Content Operator pod: {pod}", style="yellow"))
                progress.log()

                init_containers = operator_details["init_containers"]

                self.collect_pod_info(progress, pod_path, pod, init_containers, "operator", container_name="manager" )

                # Collect Operator Logs
                progress.log(f"Collecting Operator logs")
                progress.log()
                path = os.path.join(
                    f"{pod_path}",
                    f"operator.log",
                )
                container_response = self._kube.get_container_logs(pod, self._namespace, container="manager")
                write_log_to_file(container_response, path)


        except Exception as e:
            self._logger.info("Unable to retrieve Content Operator, caught %s Skipping...", e)
            progress.log(Text(f"Unable to retrieve Content Operator Logs", style="bold red"))
            progress.log()

    # Function to collect environment variables
    def get_environment_variables(self, pod, folder_path, progress):
        try:
            progress.log(f"Collecting environment variables")
            progress.log()
            command = ["printenv"]
            env_vars = self._kube.pod_exec(pod, self._namespace, command)
            local_path = os.path.join(
                f"{folder_path}", "environment_variables.txt"
            )
            with open(local_path, "w", encoding="utf8") as f:
                f.write(env_vars)

        except Exception as e:
            self._logger.info(
                "Unable to copy from pod, caught %s Skipping...", e
            )
            progress.log(
                Text(f"Unable to copy from pod", style="bold red")
            )
            progress.log()

    # Function to collect Product Version
    def get_component_version(self, pod, folder_path, progress):
        try:
            progress.log(f"Collecting component version")
            progress.log()
            command = ["cat", "/opt/ibm/version.txt"]
            version = self._kube.pod_exec(pod, self._namespace, command)
            local_path = os.path.join(
                f"{folder_path}", "version.txt"
            )
            with open(local_path, "w", encoding="utf8") as f:
                f.write(version)

        except Exception as e:
            self._logger.info(
                "Unable to copy from pod, caught %s Skipping...", e
            )
            progress.log(
                Text(f"Unable to copy from pod", style="bold red")
            )
            progress.log()

    # Function to collect Liberty Version
    def get_liberty_version(self, pod, folder_path, progress):
        try:
            progress.log(f"Collecting liberty version")
            progress.log()
            command = ["/opt/ibm/wlp/bin/server", "version"]
            version = self._kube.pod_exec(pod, self._namespace, command)
            local_path = os.path.join(
                f"{folder_path}", "liberty_version.txt"
            )
            with open(local_path, "w", encoding="utf8") as f:
                f.write(version)

        except Exception as e:
            self._logger.info(
                "Unable to copy from pod, caught %s Skipping...", e
            )
            progress.log(
                Text(f"Unable to copy from pod", style="bold red")
            )
            progress.log()

    # Function to collect Python Version
    def get_python_version(self, pod, folder_path, progress):
        try:
            progress.log(f"Collecting Python version")
            progress.log()
            command = ["python3", "--version"]
            version = self._kube.pod_exec(pod, self._namespace, command)
            local_path = os.path.join(
                f"{folder_path}", "python_version.txt"
            )
            with open(local_path, "w", encoding="utf8") as f:
                f.write(version)

        except Exception as e:
            self._logger.info(
                "Unable to copy from pod, caught %s Skipping...", e
            )
            progress.log(
                Text(f"Unable to copy from pod", style="bold red")
            )
            progress.log()

    def get_python_packages(self, pod, folder_path, progress):
        try:
            progress.log(f"Collecting Python packages")
            progress.log()
            command = ["pip", "freeze"]
            packages = self._kube.pod_exec(pod, self._namespace, command)
            local_path = os.path.join(
                f"{folder_path}", "python_packages.txt"
            )
            with open(local_path, "w", encoding="utf8") as f:
                f.write(packages)

        except Exception as e:
            self._logger.info(
                "Unable to copy from pod, caught %s Skipping...", e
            )
            progress.log(
                Text(f"Unable to copy from pod", style="bold red")
            )
            progress.log()
